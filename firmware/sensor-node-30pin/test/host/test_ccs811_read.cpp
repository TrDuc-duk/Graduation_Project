#include "Wire.h"
#include "drivers/ccs811.h"
#include "common/packet.h"
#include <cstdio>
#include <cstdlib>
std::vector<uint8_t> result;
int statusValue=0x98,writeResult=0;
bool shortRead=false;
unsigned long clockMs=0;
void set(uint16_t co2, uint16_t tvoc) {
 result={uint8_t(co2>>8),uint8_t(co2),uint8_t(tvoc>>8),uint8_t(tvoc),0x98,0,0,0};
 statusValue=0x98;writeResult=0;shortRead=false;clockMs=0;
}
void check(bool ok,const char* label) {
 if(!ok) { std::printf("FAIL: %s\n",label);std::exit(1); }
}
int main() {
 uint16_t c,t;
 set(2359,1477);
 check(ccs811_read(&c,&t)&&c==2359&&t==1477,"valid TVOC above old limit is retained");
 set(29206,32768);
 check(ccs811_read(&c,&t)&&c==29206&&t==32768,"datasheet upper boundary accepted");
 set(400,0);
 check(ccs811_read(&c,&t)&&c==400&&t==0,"zero TVOC with valid eCO2 is valid");
 set(2359,1477);shortRead=true;
 check(!ccs811_read(&c,&t)&&c==SENSOR_ERROR_U16&&t==SENSOR_ERROR_U16,"short I2C frame rejected");
 set(2359,1477);writeResult=2;
 check(!ccs811_read(&c,&t)&&c==SENSOR_ERROR_U16,"NACK is error, not warming up");
 set(2359,1477);result[4]|=1;result[5]=0x10;
 check(!ccs811_read(&c,&t)&&c==SENSOR_ERROR_U16,"sensor error flag rejected");
 set(2359,1477);statusValue=0x90;
 check(!ccs811_read(&c,&t)&&c==0&&t==0,"not ready stays distinct from errors");
 set(0,0);
 check(!ccs811_read(&c,&t)&&c==0&&t==0,"startup zero is not a successful gas reading");
 set(2359,65535);
 check(!ccs811_read(&c,&t)&&c==SENSOR_ERROR_U16,"out of range frame rejected");
 std::puts("PASS: CCS811 ranges, startup, ready flag, sensor errors, short reads and NACK");
}
