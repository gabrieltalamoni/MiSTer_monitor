// GPL-3.0-or-later — Private, bounded JPEG cache. All SD access stays on the UI task.
#pragma once
static const char* LIBRARY_CACHE_DIR="/library-cache-v1";
static const char* LIBRARY_CACHE_PART="/library-cache-v1/pending.part";
static const size_t LIBRARY_CACHE_MAX_BYTES=16*1024*1024;
static const int LIBRARY_CACHE_MAX_FILES=128;

static bool libraryCoverIdValid(const String& id) {
  if (id.length()!=24) return false;
  for (unsigned i=0;i<id.length();++i)
    if (!((id[i]>='0' && id[i]<='9') || (id[i]>='a' && id[i]<='f'))) return false;
  return true;
}
static String libraryCoverPath(const String& id) {
  return libraryCoverIdValid(id) ? String(LIBRARY_CACHE_DIR)+"/"+id+".jpg" : String();
}

static bool libraryCacheRoom(size_t incoming,const String& keep) {
  for (;;) {
    File dir=SD.open(LIBRARY_CACHE_DIR);
    if (!dir || !dir.isDirectory()) return false;
    size_t bytes=0; int count=0; String victim;
    File file=dir.openNextFile();
    while (file) {
      String name=file.name(); name=name.substring(name.lastIndexOf('/')+1);
      if (!file.isDirectory() && name.length()==28 && name.endsWith(".jpg") &&
          libraryCoverIdValid(name.substring(0,24))) {
        String path=String(LIBRARY_CACHE_DIR)+"/"+name;
        ++count; bytes+=file.size();
        if (!victim.length() && path!=keep) victim=path;
      }
      file.close(); file=dir.openNextFile();
    }
    dir.close();
    if (count<LIBRARY_CACHE_MAX_FILES && bytes+incoming<=LIBRARY_CACHE_MAX_BYTES) return true;
    if (!victim.length() || !SD.remove(victim.c_str())) return false;
  }
}

static bool libraryCacheStore(const String& id,const uint8_t* bytes,size_t size) {
  String path=libraryCoverPath(id);
  if (!sdCardAvailable || !path.length() || !bytes || size<4 || size>1024*1024 ||
      bytes[0]!=0xFF || bytes[1]!=0xD8) return false;
  if (!SD.exists(LIBRARY_CACHE_DIR) && !SD.mkdir(LIBRARY_CACHE_DIR)) return false;
  if (!libraryCacheRoom(size,path)) return false;
  SD.remove(LIBRARY_CACHE_PART);
  File file=SD.open(LIBRARY_CACHE_PART,FILE_WRITE);
  if (!file) return false;
  bool ok=file.write(bytes,size)==size;
  file.close();
  if (ok) {
    if (SD.exists(path.c_str())) SD.remove(path.c_str());
    ok=SD.rename(LIBRARY_CACHE_PART,path.c_str());
  }
  if (!ok) SD.remove(LIBRARY_CACHE_PART);
  return ok;
}
