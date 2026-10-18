// GPL-3.0-or-later — Library HTTP work. Never touches SD, the panel or UI Strings.
#pragma once
#include <atomic>
#include <new>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

static std::atomic<uint32_t> libraryNetGeneration{0};
static QueueHandle_t libraryNetInput = nullptr, libraryNetOutput = nullptr;

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
  bool page=true, ok=false;
  int index=-1;
  String url, body, notice;
  uint8_t* data=nullptr;
  size_t size=0;
  ~LibraryNetJob() { free(data); }
};

static void libraryFetchCover(LibraryNetJob& job) {
  WiFiClient client; HTTPClient http;
  http.setConnectTimeout(1200); http.setTimeout(2000);
  if (!http.begin(client,job.url)) return;
  int code=http.GET(), size=http.getSize();
  if (code!=200 || size<4 || size>1024*1024 ||
      job.generation!=libraryNetGeneration.load()) { http.end(); return; }
  job.data=(uint8_t*)ps_malloc(size);
  if (!job.data) job.data=(uint8_t*)malloc(size);
  if (!job.data) { http.end(); return; }
  WiFiClient* stream=http.getStreamPtr();
  size_t got=0; unsigned long started=millis();
  while (got<(size_t)size && millis()-started<8000 &&
         job.generation==libraryNetGeneration.load()) {
    int available=stream->available();
    if (available>0) {
      size_t want=min((size_t)2048,min((size_t)available,(size_t)size-got));
      int count=stream->readBytes(job.data+got,want);
      if (count<=0) break;
      got+=count;
      // Let the UI and idle/watchdog tasks run during sustained transfers.
      vTaskDelay(1);
    } else { if (!http.connected()) break; vTaskDelay(pdMS_TO_TICKS(1)); }
  }
  http.end();
  job.ok=got==(size_t)size && job.data[0]==0xFF && job.data[1]==0xD8;
  if (job.ok) job.size=got;
}

static void libraryNetworkTask(void*) {
  for (;;) {
    LibraryNetJob* job=nullptr;
    if (xQueueReceive(libraryNetInput,&job,portMAX_DELAY)!=pdTRUE || !job) continue;
    if (job->generation!=libraryNetGeneration.load()) { delete job; continue; }
    if (job->page) {
      JsonDocument doc;
      job->ok=libraryFetchJson(job->url,doc,job->notice);
      if (job->ok) serializeJson(doc,job->body);
    } else libraryFetchCover(*job);
    // Ownership passes back to the UI, including stale/cancelled results.
    xQueueSend(libraryNetOutput,&job,portMAX_DELAY);
  }
}

static bool libraryNetworkStart() {
  if (libraryNetInput && libraryNetOutput) return true;
  libraryNetInput=xQueueCreate(1,sizeof(LibraryNetJob*));
  libraryNetOutput=xQueueCreate(1,sizeof(LibraryNetJob*));
  if (libraryNetInput && libraryNetOutput &&
      xTaskCreate(libraryNetworkTask,"library-http",12288,nullptr,1,nullptr)==pdPASS) return true;
  if (libraryNetInput) vQueueDelete(libraryNetInput);
  if (libraryNetOutput) vQueueDelete(libraryNetOutput);
  libraryNetInput=libraryNetOutput=nullptr;
  return false;
}

static bool libraryNetworkSubmit(LibraryNetJob* job) {
  if (!libraryNetworkStart()) return false;
  LibraryNetJob* old=nullptr;
  // Keep at most the most recent queued navigation request.
  if (xQueueReceive(libraryNetInput,&old,0)==pdTRUE) delete old;
  return xQueueSend(libraryNetInput,&job,0)==pdTRUE;
}
