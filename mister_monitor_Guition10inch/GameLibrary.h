// MiSTer Monitor — Guition touch game browser
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <ArduinoJson.h>

// Native 1280x720 canvas, matching the Guition HAL's existing touch mapping.
// This module owns the panel only while active. No changes to ROMs or cores.
static bool libraryActive = false;
static bool libraryDirty = true;
static bool libraryFavorites = false;
static bool libraryKeyboard = false;
static String libraryFolder, libraryUp, libraryQuery, libraryToken, libraryNotice;
static int libraryPage = 1, libraryPages = 1, libraryTotal = 0;
static int librarySelected = -1;
static const int LIBRARY_PAGE_SIZE = 6;
// Listing only populated systems can take longer than 10 s on a real card.
// HTTPClient::setTimeout takes uint16_t milliseconds (maximum 65535).
static const uint16_t LIBRARY_REQUEST_TIMEOUT_MS = 60000;
struct LibraryItem {
  String id, name, path, system;
  bool folder = false, favorite = false;
};
static LibraryItem libraryItems[LIBRARY_PAGE_SIZE];
static int libraryCount = 0;
static const uint16_t LIB_BG = 0x0863, LIB_PANEL = 0x10E5, LIB_LINE = 0x2988;
static const uint16_t LIB_TEXT = 0xEF7E, LIB_MUTED = 0x9D96, LIB_MINT = 0x9F36;

static String libraryEncode(const String& value) {
  static const char hex[] = "0123456789ABCDEF";
  String out;
  out.reserve(value.length() * 3);
  for (size_t i = 0; i < value.length(); ++i) {
    unsigned char c = value[i];
    if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
        (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.') out += char(c);
    else { out += '%'; out += hex[c >> 4]; out += hex[c & 15]; }
  }
  return out;
}

static bool libraryRequest(const String& route, JsonDocument& result,
                           const JsonDocument* payload = nullptr) {
  if (WiFi.status() != WL_CONNECTED || strlen(misterIP) == 0) {
    libraryNotice = "Sem conexao. Configure WiFi e o endereco do MiSTer.";
    return false;
  }
  WiFiClient client;
  HTTPClient http;
  http.setTimeout(LIBRARY_REQUEST_TIMEOUT_MS);
  if (!http.begin(client, String("http://") + misterIP + ":8081" + route)) {
    libraryNotice = "Nao foi possivel conectar ao servidor.";
    return false;
  }
  int code;
  if (payload) {
    String body;
    serializeJson(*payload, body);
    http.addHeader("Content-Type", "application/json");
    code = http.POST(body);
  } else code = http.GET();
  if (code <= 0) {
    libraryNotice = code == HTTPC_ERROR_READ_TIMEOUT
      ? "Tempo limite (60s). Toque em Atualizar."
      : "Falha de conexao (" + String(code) + "): " + HTTPClient::errorToString(code);
    http.end();
    return false;
  }
  int size = http.getSize();
  if (size < 0) {
    libraryNotice = "HTTP " + String(code) + ": resposta sem tamanho. Reinicie o MiSTer_Monitor.";
    http.end();
    return false;
  }
  if (size > 24576) {
    libraryNotice = "Resposta grande demais (" + String(size) + " bytes). Atualize o servidor.";
    http.end();
    return false;
  }
  // The server uses Content-Length. Parse only bounded, small page responses.
  String body = http.getString();
  http.end();
  if (body.length() != (size_t)size) {
    libraryNotice = "Resposta incompleta. Toque em Atualizar.";
    return false;
  }
  DeserializationError error = deserializeJson(result, body);
  if (error) {
    libraryNotice = "HTTP " + String(code) + ": JSON invalido. Confira o servidor da biblioteca.";
    return false;
  }
  if (code != 200) {
    libraryNotice = result["error"].as<String>();
    if (!libraryNotice.length()) libraryNotice = "Erro HTTP " + String(code);
    return false;
  }
  return true;
}

static void libraryText(const String& text, int x, int y, int size, uint16_t color,
                        int maxWidth = 1200) {
  Board.Display.setFont(&fonts::Font0);
  Board.Display.setTextSize(size);
  Board.Display.setTextColor(color);
  String fitted = text;
  while (fitted.length() && Board.Display.textWidth(fitted.c_str()) > maxWidth) {
    // Remove an entire UTF-8 codepoint before appending the ellipsis.
    int end = fitted.length() - 1;
    while (end > 0 && (uint8_t(fitted[end]) & 0xC0) == 0x80) --end;
    fitted.remove(end);
  }
  if (fitted != text) {
    while (fitted.length() && Board.Display.textWidth((fitted + "...").c_str()) > maxWidth) {
      int end = fitted.length() - 1;
      while (end > 0 && (uint8_t(fitted[end]) & 0xC0) == 0x80) --end;
      fitted.remove(end);
    }
    fitted += "...";
  }
  Board.Display.setCursor(x, y);
  Board.Display.print(fitted);
}

static void libraryButton(int x, int y, int w, const String& text, bool active = false) {
  Board.Display.fillRoundRect(x, y, w, 48, 9, active ? LIB_MINT : LIB_PANEL);
  Board.Display.drawRoundRect(x, y, w, 48, 9, LIB_LINE);
  libraryText(text, x + 14, y + 15, 2, active ? LIB_BG : LIB_TEXT, w - 25);
}

static void libraryLoad() {
  libraryNotice = "Lendo o microSD...";
  Board.Display.fillRect(0, 660, 1280, 60, LIB_BG);
  libraryText(libraryNotice, 28, 674, 2, LIB_MINT);
  JsonDocument doc;
  String route = "/library/page?per=6&page=" + String(libraryPage) +
    "&folder=" + libraryEncode(libraryFolder) + "&q=" + libraryEncode(libraryQuery) +
    "&favorites=" + String(libraryFavorites ? 1 : 0);
  libraryCount = 0;
  librarySelected = -1;
  if (libraryRequest(route, doc)) {
    libraryToken = doc["token"].as<String>();
    libraryUp = doc["up"].as<String>();
    libraryPage = doc["page"] | 1;
    libraryPages = doc["pages"] | 1;
    libraryTotal = doc["total"] | 0;
    for (JsonObject item : doc["items"].as<JsonArray>()) {
      if (libraryCount >= LIBRARY_PAGE_SIZE) break;
      LibraryItem& target = libraryItems[libraryCount++];
      target.id = item["id"].as<String>(); target.name = item["name"].as<String>();
      target.path = item["path"].as<String>(); target.system = item["system"].as<String>();
      target.folder = item["kind"].as<String>() == "folder";
      target.favorite = item["favorite"] | false;
    }
    libraryNotice = libraryCount ? "Toque em uma capa para escolher o jogo." :
      (libraryFavorites ? "Nenhum favorito. Escolha um jogo e toque em Favoritar." : "Nenhum jogo nesta pasta ou busca.");
  } else { libraryPages = 1; libraryTotal = 0; }
  libraryDirty = true;
}

// Download one image at a time to a reusable scratch file. Disk and memory stay
// bounded even when browsing a large collection. Missing covers are explicit.
static bool libraryDrawCover(const LibraryItem& item, int x, int y, int w, int h) {
  if (!sdCardAvailable) return false;
  WiFiClient client;
  HTTPClient http;
  http.setTimeout(2500);
  if (!http.begin(client, String("http://") + misterIP + ":8081/library/artwork?id=" + item.id)) return false;
  int code = http.GET();
  int size = http.getSize();
  if (code != 200 || size < 4 || size > 1024 * 1024) { http.end(); return false; }
  const char* path = "/.library-cover.jpg";
  File file = SD.open(path, FILE_WRITE);
  if (!file) { http.end(); return false; }
  size_t written = 0;
  uint8_t chunk[2048];
  WiFiClient* stream = http.getStreamPtr();
  unsigned long progress = millis();
  while (written < (size_t)size && millis() - progress < 2500) {
    int avail = stream->available();
    if (avail > 0) {
      size_t want = min(sizeof(chunk), min((size_t)avail, (size_t)size - written));
      int got = stream->readBytes(chunk, want);
      if (got <= 0 || file.write(chunk, got) != (size_t)got) break;
      written += got; progress = millis();
    } else { if (!http.connected()) break; delay(1); }
  }
  file.close(); http.end();
  bool ok = written == (size_t)size;
  if (ok) { PngConvInfo info; ok = drawJpegInBox(path, x, y, w, h, false, nullptr, &info); }
  SD.remove(path);
  return ok;
}

static void libraryDrawKeyboard() {
  Board.Display.fillRect(16, 178, 1248, 478, LIB_BG);
  libraryText("BUSCAR NESTA PASTA", 38, 194, 2, LIB_MINT);
  libraryText(libraryQuery + "_", 38, 232, 3, LIB_TEXT, 1170);
  const char* rows[] = {"QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM", "1234567890"};
  for (int row = 0; row < 4; ++row)
    for (int col = 0; rows[row][col]; ++col)
      libraryButton(34 + col * 120, 284 + row * 66, 108, String(rows[row][col]));
  libraryButton(34, 558, 180, "Cancelar"); libraryButton(232, 558, 220, "Espaco");
  libraryButton(470, 558, 220, "Apagar"); libraryButton(708, 558, 220, "Limpar");
  libraryButton(946, 558, 288, "Buscar", true);
}

static void libraryDraw() {
  libraryDirty = false;
  Board.Display.fillScreen(LIB_BG);
  libraryText("MISTER MONITOR / GUITION", 28, 22, 2, LIB_MINT);
  libraryText("Sua proxima partida.", 28, 57, 4, LIB_TEXT);
  libraryButton(28, 112, 160, "Sistemas", !libraryFolder.length() && !libraryFavorites);
  libraryButton(200, 112, 180, "Favoritos", libraryFavorites);
  libraryButton(392, 112, 140, "Voltar");
  libraryButton(544, 112, 190, "Buscar");
  libraryButton(746, 112, 190, "Atualizar");
  libraryButton(1054, 32, 198, "Monitor");
  if (libraryKeyboard) { libraryDrawKeyboard(); return; }
  String folderLabel = libraryFavorites ? "Seus favoritos" :
    (libraryFolder.length() ? libraryFolder.substring(11) : "Escolha um sistema");
  libraryText(folderLabel, 28, 182, 2, LIB_MUTED, 970);
  libraryText(String(libraryTotal) + " itens", 1110, 182, 2, LIB_MUTED, 150);
  for (int i = 0; i < libraryCount; ++i) {
    int x = 28 + (i % 6) * 208, y = 220;
    const LibraryItem& item = libraryItems[i];
    Board.Display.fillRoundRect(x, y, 192, 350, 12, LIB_PANEL);
    Board.Display.drawRoundRect(x, y, 192, 350, 12, LIB_LINE);
    if (item.folder) {
      Board.Display.drawRoundRect(x+52, y+65, 88, 66, 8, LIB_MINT);
      Board.Display.fillRect(x+52, y+56, 38, 14, LIB_MINT);
      libraryText("ABRIR", x+66, y+163, 2, LIB_MINT);
    } else if (!libraryDrawCover(item, x+10, y+10, 172, 242)) {
      libraryText("Sem capa", x+44, y+114, 2, LIB_MUTED, 150);
    }
    libraryText(item.name, x+12, y+273, 2, LIB_TEXT, 168);
    libraryText(item.folder ? "PASTA" : item.system, x+12, y+312, 1, LIB_MUTED, 168);
    if (item.favorite) libraryText("*", x+164, y+10, 3, LIB_MINT, 25);
  }
  libraryButton(28, 600, 200, "Anterior");
  libraryText(String(libraryPage) + " / " + String(libraryPages), 586, 616, 2, LIB_TEXT, 140);
  libraryButton(1052, 600, 200, "Proxima");
  libraryText(libraryNotice, 28, 678, 2, LIB_MUTED, 1220);
}

static void libraryDetails() {
  const LibraryItem& item = libraryItems[librarySelected];
  Board.Display.fillRoundRect(180, 208, 920, 340, 18, LIB_PANEL);
  Board.Display.drawRoundRect(180, 208, 920, 340, 18, LIB_MINT);
  libraryText(item.name, 212, 240, 3, LIB_TEXT, 850);
  libraryText(item.system, 212, 289, 2, LIB_MINT, 850);
  libraryText("Trocar de jogo encerra a partida atual.", 212, 344, 2, LIB_TEXT, 850);
  libraryText("Salve seu progresso antes de continuar.", 212, 380, 2, LIB_MUTED, 850);
  libraryButton(212, 454, 220, "Cancelar");
  libraryButton(458, 454, 270, item.favorite ? "Desfavoritar" : "Favoritar");
  libraryButton(754, 454, 312, "Iniciar jogo", true);
}

static bool libraryInside(int x, int y, int bx, int by, int w, int h = 48) {
  return x >= bx && x < bx+w && y >= by && y < by+h;
}

static void libraryClose() {
  libraryActive = false; librarySelected = -1;
  showingCoreImage = false; currentPage = 0;
  backgroundLoaded = false; needsRedraw = true; lastButtonPress = millis();
}

static void libraryTouch(int x, int y) {
  if (librarySelected >= 0) {
    if (libraryInside(x,y,212,454,220)) { librarySelected=-1; libraryDirty=true; }
    else if (libraryInside(x,y,458,454,270) || libraryInside(x,y,754,454,312)) {
      bool launch = libraryInside(x,y,754,454,312);
      LibraryItem item = libraryItems[librarySelected];
      JsonDocument body, response;
      body["token"] = libraryToken; body["id"] = item.id;
      if (launch) body["confirmed"] = true;
      else body["enabled"] = !item.favorite;
      // The blocking request consumes this touch edge exactly once.
      if (libraryRequest(launch ? "/library/launch" : "/library/favorite", response, &body)) {
        if (!launch) {
          libraryLoad();
          libraryNotice = item.favorite ? "Removido dos favoritos." : "Salvo nos favoritos.";
        } else libraryNotice = "Lancamento solicitado. Confira o jogo na TV.";
      }
      librarySelected=-1; libraryDirty=true;
    }
    return;
  }
  if (libraryInside(x,y,1054,32,198)) { libraryClose(); return; }
  if (libraryKeyboard) {
    const char* rows[] = {"QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM", "1234567890"};
    for(int row=0;row<4;++row) for(int col=0;rows[row][col];++col)
      if(libraryInside(x,y,34+col*120,284+row*66,108) && libraryQuery.length()<60) libraryQuery+=rows[row][col];
    if(libraryInside(x,y,34,558,180)) libraryKeyboard=false;
    if(libraryInside(x,y,232,558,220) && libraryQuery.length()<60) libraryQuery+=' ';
    if(libraryInside(x,y,470,558,220) && libraryQuery.length()) libraryQuery.remove(libraryQuery.length()-1);
    if(libraryInside(x,y,708,558,220)) libraryQuery="";
    if(libraryInside(x,y,946,558,288)) { libraryKeyboard=false; libraryPage=1; libraryLoad(); }
    libraryDirty=true; return;
  }
  if (libraryInside(x,y,28,112,160)) { libraryFolder="";libraryFavorites=false;libraryPage=1;libraryQuery="";libraryLoad(); }
  else if (libraryInside(x,y,200,112,180)) { libraryFavorites=true;libraryPage=1;libraryQuery="";libraryLoad(); }
  else if (libraryInside(x,y,392,112,140)) { libraryFolder=libraryUp;libraryFavorites=false;libraryPage=1;libraryQuery="";libraryLoad(); }
  else if (libraryInside(x,y,544,112,190)) { libraryKeyboard=true;libraryDirty=true; }
  else if (libraryInside(x,y,746,112,190)) libraryLoad();
  else if (libraryInside(x,y,28,600,200) && libraryPage>1) { --libraryPage;libraryLoad(); }
  else if (libraryInside(x,y,1052,600,200) && libraryPage<libraryPages) { ++libraryPage;libraryLoad(); }
  else for (int i=0;i<libraryCount;++i) if (libraryInside(x,y,28+i*208,220,192,350)) {
    if(libraryItems[i].folder) { libraryFolder=libraryItems[i].path;libraryQuery="";libraryPage=1;libraryLoad(); }
    else { librarySelected=i;libraryDetails(); }
    break;
  }
}

static void libraryOpen() {
  libraryActive=true;libraryKeyboard=false;libraryLoad();
}

// Drawn last in the normal monitor loop, so it is a visible touch target on
// both the HUD and artwork pages. The entry is outside the existing footer.
static void libraryDrawEntry() {
  libraryButton(1030, 8, 230, "Biblioteca");
}
