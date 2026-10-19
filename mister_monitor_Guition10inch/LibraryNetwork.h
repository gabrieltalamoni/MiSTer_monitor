// GPL-3.0-or-later — Library HTTP work. Never touches SD, the panel or UI Strings.
#pragma once
#include <atomic>
#include <new>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

static std::atomic<uint32_t> libraryNetGeneration{0};
static QueueHandle_t libraryNetInput = nullptr, libraryCoverInput = nullptr, libraryNetOutput = nullptr;

static bool libraryFetchJson(const String& url, JsonDocument& result, String& notice,
                             const JsonDocument* payload = nullptr) {
  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(3000);
  http.setTimeout(60000);
  if (!http.begin(client, url)) { notice="Nao foi possivel conectar ao servidor."; return false; }
  int code;
  if (payload) {
    String body; serializeJson(*payload, body);
    http.addHeader("Content-Type", "application/json");
    code=http.POST(body);
  } else code=http.GET();
  if (code<=0) {
    notice=code==HTTPC_ERROR_READ_TIMEOUT ? "Tempo limite (60s). Toque em Atualizar." :
      "Falha de conexao ("+String(code)+"): "+HTTPClient::errorToString(code);
    http.end(); return false;
  }
  int size=http.getSize();
  if (size<0 || size>24576) {
    notice=size<0 ? "HTTP "+String(code)+": resposta sem tamanho." :
      "Resposta grande demais ("+String(size)+" bytes).";
    http.end(); return false;
  }
  String body=http.getString(); http.end();
  if (body.length()!=(size_t)size) { notice="Resposta incompleta. Toque em Atualizar."; return false; }
  if (deserializeJson(result,body)) { notice="HTTP "+String(code)+": JSON invalido."; return false; }
  if (code!=200) {
    notice=result["error"].as<String>();
    if (!notice.length()) notice="Erro HTTP "+String(code);
    return false;
  }
  return true;
}

struct LibraryNetJob {
  uint32_t generation=0;
  bool page=true, logo=false, ok=false;
  int index=-1;
  String url, body, notice;
  String ssAuth, ssSystem, ssName, ssOrder, ssRegion;
  bool ssConfigured=false, ssEnabled=true;
  uint8_t* data=nullptr;
  size_t size=0;
  ~LibraryNetJob() { free(data); }
};

// writeToStream decodes chunked transfer. Limit memory and cancel obsolete work.
class LibraryBodySink : public Stream {
 public:
  uint8_t* bytes=nullptr; size_t size=0, limit; uint32_t generation;
  bool failed=false; unsigned long started=millis();
  LibraryBodySink(size_t max,uint32_t gen):limit(max),generation(gen) {
    bytes=(uint8_t*)ps_malloc(limit);
    if (!bytes) bytes=(uint8_t*)malloc(limit);
  }
  ~LibraryBodySink() { free(bytes); }
  size_t write(uint8_t c) override { return write(&c,1); }
  size_t write(const uint8_t* data,size_t n) override {
    if (!bytes || n>limit-size || generation!=libraryNetGeneration.load() ||
        millis()-started>45000) { failed=true; return 0; }
    memcpy(bytes+size,data,n); size+=n; vTaskDelay(1); return n;
  }
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
  void flush() override {}
};

static String libraryUrlEncode(const String& value) {
  static const char hex[]="0123456789ABCDEF"; String out;
  for (unsigned i=0;i<value.length();++i) {
    unsigned char c=value[i];
    if (isalnum(c) || c=='-' || c=='_' || c=='.') out+=(char)c;
    else { out+='%'; out+=hex[c>>4]; out+=hex[c&15]; }
  }
  return out;
}

// Remove only dump/region annotations for name matching; never choose the first
// fuzzy ScreenScraper hit. Multiple different exact matches are ambiguous.
static String libraryMatchName(String name) {
  String out; int depth=0;
  name.toLowerCase();
  for (unsigned i=0;i<name.length();++i) {
    char c=name[i];
    if (c=='(' || c=='[') { ++depth; continue; }
    if (c==')' || c==']') { if (depth) --depth; continue; }
    if (!depth && (isalnum((unsigned char)c) || (unsigned char)c>=128)) out+=c;
  }
  return out;
}

static int libraryDownload(LibraryNetJob& job,const String& url,size_t limit,
                           bool jpeg) {
  HTTPClient http;
  http.setConnectTimeout(5000); http.setTimeout(30000);
  // HTTPS follows the same transport used by the original ScreenScraper code.
  if (!http.begin(url)) return -1;
  int code=http.GET();
  if (code!=200 || job.generation!=libraryNetGeneration.load()) {
    http.end(); return code;
  }
  int length=http.getSize();
  if (length>(int)limit) { http.end(); return -2; }
  LibraryBodySink sink(limit,job.generation);
  int received=sink.bytes ? http.writeToStream(&sink) : -1;
  http.end();
  if (received<0 || sink.failed || !sink.size ||
      (length>=0 && sink.size!=(size_t)length)) return -3;
  if (jpeg && (sink.size<4 || sink.bytes[0]!=0xFF || sink.bytes[1]!=0xD8)) return -4;
  free(job.data); job.data=sink.bytes; sink.bytes=nullptr;
  job.size=sink.size; job.ok=true; return 200;
}

static String libraryMediaName(String token) {
  token.trim(); token.toLowerCase();
  if (token=="box3d") return "box-3D";
  if (token=="box2d") return "box-2D";
  if (token=="mix" || token=="mix2") return "mixrbv2";
  if (token=="mix1") return "mixrbv1";
  if (token=="screenshot") return "ss";
  if (token=="titlescreen") return "sstitle";
  if (token=="wheel" || token=="wheel-carbon" || token=="wheel-steel" ||
      token=="fanart" || token=="marquee") return token;
  return String();
}

static unsigned long librarySSBlockedUntil=0;
static void libraryFetchCover(LibraryNetJob& job) {
  int code=libraryDownload(job,job.url,1024*1024,true);
  if (job.ok) return;
  if (code!=404) {
    job.notice="Capa local: falha HTTP "+String(code)+". Toque em Atualizar."; return;
  }
  if (!job.ssEnabled) { job.notice="Sem capa local; download automatico desativado."; return; }
  if (!job.ssConfigured) {
    job.notice="Sem capa local. Configure ss_dev_user/ss_dev_pass do ScreenScraper."; return;
  }
  if (!job.ssSystem.length() || !libraryMatchName(job.ssName).length()) return;
  if ((long)(millis()-librarySSBlockedUntil)<0) {
    job.notice="ScreenScraper em pausa por limite ou autenticacao. Tente depois."; return;
  }
  if (job.generation!=libraryNetGeneration.load()) return;
  String base="https://api.screenscraper.fr/api2/";
  code=libraryDownload(job,base+"jeuRecherche.php?"+job.ssAuth+
      "&output=json&systemeid="+job.ssSystem+"&recherche="+
      libraryUrlEncode(job.ssName),256*1024,false);
  if (code!=200) {
    if (code==401 || code==403 || code==429) librarySSBlockedUntil=millis()+300000;
    job.notice="ScreenScraper: HTTP "+String(code)+". Confira configuracao/limites."; return;
  }
  JsonDocument filter,doc;
  filter["response"]["jeux"][0]["id"]=true;
  filter["response"]["jeux"][0]["systeme"]["id"]=true;
  filter["response"]["jeux"][0]["noms"][0]["text"]=true;
  auto error=deserializeJson(doc,job.data,job.size,DeserializationOption::Filter(filter));
  free(job.data); job.data=nullptr; job.size=0; job.ok=false;
  if (error) { job.notice="ScreenScraper: resposta invalida."; return; }
  String gameId,query=libraryMatchName(job.ssName);
  for (JsonObject game:doc["response"]["jeux"].as<JsonArray>()) {
    if (game["systeme"]["id"].as<String>()!=job.ssSystem) continue;
    bool exact=false;
    for (JsonObject name:game["noms"].as<JsonArray>())
      if (libraryMatchName(name["text"].as<String>())==query) exact=true;
    if (!exact) continue;
    String id=game["id"].as<String>();
    if (gameId.length() && gameId!=id) {
      job.notice="ScreenScraper: titulo ambiguo; nenhuma capa escolhida."; return;
    }
    gameId=id;
  }
  if (!gameId.length()) { job.notice="ScreenScraper: jogo sem correspondencia exata."; return; }
  // Same configured media order and preferred region as the original monitor.
  // Bound work to four media requests per visit; cancelled pages stop here.
  int attempts=0,at=0;
  while (at<(int)job.ssOrder.length() && attempts<4) {
    int end=job.ssOrder.indexOf(',',at); if (end<0) end=job.ssOrder.length();
    String media=libraryMediaName(job.ssOrder.substring(at,end)); at=end+1;
    if (!media.length()) continue;
    for (int region=0;region<2 && attempts<4;++region) {
      if (job.generation!=libraryNetGeneration.load()) return;
      String suffix=region==0 ? job.ssRegion : "wor";
      if (region==1 && job.ssRegion=="wor") continue;
      String type=media;
      if (media!="fanart") type+="("+suffix+")";
      else if (region) continue;
      ++attempts;
      code=libraryDownload(job,base+"mediaJeu.php?"+job.ssAuth+
          "&systemeid="+job.ssSystem+"&jeuid="+gameId+"&crc=&md5=&sha1=&media="+
          libraryUrlEncode(type)+"&maxwidth=172&maxheight=242&outputformat=jpg",1024*1024,true);
      if (job.ok) return;
      if (code==401 || code==403 || code==429) {
        librarySSBlockedUntil=millis()+300000;
        job.notice="ScreenScraper: autenticacao/limite HTTP "+String(code); return;
      }
    }
  }
  job.notice="ScreenScraper: capa indisponivel nesta busca.";
}

static void libraryNetworkTask(void* input) {
  QueueHandle_t queue=(QueueHandle_t)input;
  for (;;) {
    LibraryNetJob* job=nullptr;
    if (xQueueReceive(queue,&job,portMAX_DELAY)!=pdTRUE || !job) continue;
    if (job->generation!=libraryNetGeneration.load()) { delete job; continue; }
    if (job->page) {
      JsonDocument doc;
      job->ok=libraryFetchJson(job->url,doc,job->notice);
      if (job->ok) serializeJson(doc,job->body);
    } else if (job->logo) {
      libraryDownload(*job,job->url,65536,true);
    } else libraryFetchCover(*job);
    // Ownership passes back to the UI, including stale/cancelled results.
    xQueueSend(libraryNetOutput,&job,portMAX_DELAY);
  }
}

static bool libraryNetworkStart() {
  if (libraryNetInput && libraryCoverInput && libraryNetOutput) return true;
  libraryNetInput=xQueueCreate(1,sizeof(LibraryNetJob*));
  libraryCoverInput=xQueueCreate(1,sizeof(LibraryNetJob*));
  libraryNetOutput=xQueueCreate(2,sizeof(LibraryNetJob*));
  TaskHandle_t pageTask=nullptr,coverTask=nullptr;
  if (libraryNetInput && libraryCoverInput && libraryNetOutput &&
      xTaskCreate(libraryNetworkTask,"library-http",12288,libraryNetInput,1,&pageTask)==pdPASS &&
      xTaskCreate(libraryNetworkTask,"library-covers",12288,libraryCoverInput,1,&coverTask)==pdPASS) return true;
  if (pageTask) vTaskDelete(pageTask);
  if (coverTask) vTaskDelete(coverTask);
  if (libraryNetInput) vQueueDelete(libraryNetInput);
  if (libraryCoverInput) vQueueDelete(libraryCoverInput);
  if (libraryNetOutput) vQueueDelete(libraryNetOutput);
  libraryNetInput=libraryCoverInput=libraryNetOutput=nullptr;
  return false;
}

static bool libraryNetworkSubmit(LibraryNetJob* job) {
  if (!libraryNetworkStart()) return false;
  LibraryNetJob* old=nullptr;
  // Slow external artwork must never hold a navigation request behind it.
  QueueHandle_t input=job->page ? libraryNetInput : libraryCoverInput;
  if (xQueueReceive(input,&old,0)==pdTRUE) delete old;
  return xQueueSend(input,&job,0)==pdTRUE;
}
