#include "Wire.h"
#include "drivers/aht10.h"
#include "common/packet.h"
#include <cstdio>
#include <cstdlib>
std::vector<std::vector<uint8_t>> frames;
size_t frameIndex=0;
int resetCalls=0, writeResult=0;
unsigned long clockMs=0, triggeredAt=0;
std::vector<uint8_t> frame(float t, float h, uint8_t status=0x08) {
 uint32_t rt=std::lround((t+50)*1048576/200);
 uint32_t rh=std::lround(h*1048576/100);
 return {status,uint8_t(rh>>12),uint8_t(rh>>4),uint8_t((rh<<4)|(rt>>16)),uint8_t(rt>>8),uint8_t(rt)};
}
void set(std::vector<std::vector<uint8_t>> values) {
 frames=values; frameIndex=0; resetCalls=0; clockMs=0; writeResult=0;
}
void check(bool ok, const char* label) {
 if(!ok) { std::printf("FAIL: %s\n",label);std::exit(1); }
}
int main() {
 int16_t t;uint16_t h;
 set({frame(26.5,68.2)});
 check(aht10_read(&t,&h)&&t==265&&h==682&&clockMs-triggeredAt>=80&&resetCalls>0,"wait for conversion and decode packed frame");
 set({{0x08,0},frame(26.5,68.2)});
 check(aht10_read(&t,&h)&&t==265&&h==682&&resetCalls>0,"short frame must retry without publishing zeros");
 set({frame(25,50,0x88)});
 check(!aht10_read(&t,&h)&&t==SENSOR_ERROR_I16&&h==SENSOR_ERROR_U16&&clockMs<5000,"busy sensor must time out with sentinels");
 set({frame(25,50,0x00)});
 check(!aht10_read(&t,&h),"uncalibrated frame rejected");
 set({frame(25,0)});
 check(aht10_read(&t,&h)&&t==250&&h==0,"zero humidity is not silently replaced");
 set({frame(90,50)});
 check(!aht10_read(&t,&h),"out of range temperature rejected");
 set({frame(25,50)});writeResult=2;
 check(!aht10_read(&t,&h)&&t==SENSOR_ERROR_I16&&h==SENSOR_ERROR_U16,"NACK must not become a measurement");
 std::puts("PASS: conversion delay, frame decoding, short reads, busy deadline, calibration, range and NACK handling");
}
