#ifdef TEST_CCS811
#pragma once
#include "Arduino.h"
#include <vector>
extern std::vector<uint8_t> result;
extern int statusValue, writeResult;
extern bool shortRead;
class TwoWire {
 uint8_t reg=0;
 std::vector<uint8_t> current;
 size_t index=0;
public:
 void beginTransmission(uint8_t) {}
 size_t write(uint8_t value) { reg=value; return 1; }
 size_t write(const uint8_t* data, size_t size) { reg=data[0]; return size; }
 uint8_t endTransmission() { return writeResult; }
 uint8_t requestFrom(uint8_t, uint8_t) {
  current=reg==0?std::vector<uint8_t>{uint8_t(statusValue)}:result;
  if(shortRead && reg==2) current.resize(2);
  index=0;return current.size();
 }
 int read() { return current.at(index++); }
 void end() {}
 void begin(int, int) {}
 void setClock(unsigned long) {}
 void setTimeOut(unsigned long) {}
};
inline TwoWire Wire;
#else
#pragma once
#include "Arduino.h"
#include <array>
#include <vector>
extern std::vector<std::vector<uint8_t>> frames;
extern size_t frameIndex;
extern int writeResult;
extern unsigned long triggeredAt;
extern int resetCalls;
class TwoWire {
 std::vector<uint8_t> current;
 size_t index=0;
public:
 void beginTransmission(uint8_t) {}
 size_t write(const uint8_t* data, size_t size) {
  if(size==1 && data[0]==0xBA) ++resetCalls;
  if(size==3 && data[0]==0xAC) triggeredAt=clockMs;
  return size;
 }
 uint8_t endTransmission() { return writeResult; }
 uint8_t requestFrom(uint8_t, uint8_t count) {
  if(count==1) { current={0x08}; index=0; return 1; }
  // Mô phỏng cảm biến chưa chuyển đổi xong nếu đọc quá sớm.
  if(clockMs-triggeredAt<80) { current={0x08,0,0,6,0xB8,0x52}; }
  else current=frames.at(frameIndex<frames.size()?frameIndex++:frames.size()-1);
  index=0; return current.size();
 }
 int read() { return current.at(index++); }
};
inline TwoWire Wire;

#endif
