#pragma once
#include "Arduino.h"
constexpr int CCS811_DRIVE_MODE_1SEC=1;
class Adafruit_CCS811 {
public:
 bool begin(int) { return true; }
 void setDriveMode(int) {}
};
