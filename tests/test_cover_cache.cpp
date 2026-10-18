// Exercise the actual firmware cache with a deterministic in-memory SD adapter.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include <iostream>

struct String : std::string {
  using std::string::string;
  String(const std::string& s):std::string(s) {}
  String substring(size_t a) const { return substr(a); }
  String substring(size_t a,size_t b) const { return substr(a,b-a); }
  int lastIndexOf(char c) const { auto n=rfind(c); return n==npos ? -1 : int(n); }
  bool endsWith(const char* tail) const {
    size_t n=std::strlen(tail); return size()>=n && compare(size()-n,n,tail)==0;
  }
};
static String operator+(const String& a,const char* b) { return String(std::string(a)+b); }
static String operator+(const String& a,const String& b) { return String(std::string(a)+std::string(b)); }
struct Node { bool dir=false; std::vector<uint8_t> data; };
static std::map<std::string,Node> disk;
static size_t writeLimit=SIZE_MAX;
static bool renameFails=false;
struct File {
  std::string path,last;
  File(std::string p=""):path(p) {}
  explicit operator bool() const { return !path.empty() && disk.count(path); }
  bool isDirectory() const { return disk.at(path).dir; }
  const char* name() const { return path.c_str(); }
  size_t size() const { return disk.at(path).data.size(); }
  size_t write(const uint8_t* bytes,size_t n) {
    n=std::min(n,writeLimit);
    disk[path].data.insert(disk[path].data.end(),bytes,bytes+n); return n;
  }
  void close() {}
  File openNextFile() {
    std::string prefix=path+"/";
    auto it=last.empty() ? disk.lower_bound(prefix) : disk.upper_bound(last);
    for (;it!=disk.end() && it->first.compare(0,prefix.size(),prefix)==0;++it) {
      if (it->first.find('/',prefix.size())!=std::string::npos) continue;
      last=it->first; return File(last);
    }
    return File();
  }
};
#define FILE_WRITE 1
struct FakeSD {
  bool exists(const char* p) { return disk.count(p); }
  bool mkdir(const char* p) { disk[p].dir=true; return true; }
  bool remove(const char* p) { return disk.erase(p)>0; }
  File open(const char* p,int mode=0) {
    if (mode==FILE_WRITE) disk[p];
    return File(disk.count(p) ? p : "");
  }
  bool rename(const char* a,const char* b) {
    if (renameFails || !disk.count(a) || disk.count(b)) return false;
    disk[b]=std::move(disk[a]); disk.erase(a); return true;
  }
} SD;
static bool sdCardAvailable=true;
#include "../mister_monitor_Guition10inch/LibraryCoverCache.h"

static String id(unsigned n) { char s[25]; std::snprintf(s,sizeof(s),"%024x",n); return s; }
static void reset() { disk.clear(); writeLimit=SIZE_MAX; renameFails=false; sdCardAvailable=true; }
int main() {
  const uint8_t jpeg[]={0xFF,0xD8,0xFF,0xD9};
  assert(libraryCoverIdValid(id(1)));
  assert(!libraryCoverIdValid("../../../../important.jpg"));
  assert(!libraryCoverIdValid("ABCDEF012345678901234567"));
  assert(!libraryCacheStore(id(1),nullptr,4));
  reset(); disk["/important.jpg"].data={1,2,3};
  SD.mkdir(LIBRARY_CACHE_DIR); disk["/library-cache-v1/notes.txt"].data={4};
  for (unsigned i=0;i<129;++i) assert(libraryCacheStore(id(i),jpeg,sizeof(jpeg)));
  assert(!SD.exists(libraryCoverPath(id(0)).c_str()));
  assert(SD.exists(libraryCoverPath(id(128)).c_str()));
  assert(disk.count("/important.jpg") && disk.count("/library-cache-v1/notes.txt"));
  size_t count=0;
  for (const auto& pair:disk) if (pair.first.find(".jpg")!=std::string::npos && pair.first!="/important.jpg") ++count;
  assert(count==128);
  reset();
  std::vector<uint8_t> large(1024*1024,0); large[0]=0xFF; large[1]=0xD8;
  for (unsigned i=0;i<17;++i) assert(libraryCacheStore(id(i),large.data(),large.size()));
  size_t bytes=0;
  for (const auto& pair:disk) bytes+=pair.second.data.size();
  assert(bytes<=LIBRARY_CACHE_MAX_BYTES);
  assert(!SD.exists(libraryCoverPath(id(0)).c_str()));
  assert(SD.exists(libraryCoverPath(id(16)).c_str()));
  reset(); writeLimit=2;
  assert(!libraryCacheStore(id(1),jpeg,sizeof(jpeg)));
  assert(!SD.exists(libraryCoverPath(id(1)).c_str()) && !SD.exists(LIBRARY_CACHE_PART));
  reset(); renameFails=true;
  assert(!libraryCacheStore(id(1),jpeg,sizeof(jpeg)));
  assert(!SD.exists(libraryCoverPath(id(1)).c_str()) && !SD.exists(LIBRARY_CACHE_PART));
  reset(); sdCardAvailable=false;
  assert(!libraryCacheStore(id(1),jpeg,sizeof(jpeg)) && disk.empty());
  std::cout << "cover cache: bounds, eviction, path isolation and failed writes OK\n";
}
