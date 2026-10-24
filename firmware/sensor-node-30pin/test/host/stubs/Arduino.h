#pragma once
#include <cstdint>
#include <cstddef>
#include <cmath>
struct MockSerial { template<class... T> void printf(const char*, T...) {} };
inline MockSerial Serial;
extern unsigned long clockMs;
inline void delay(unsigned long ms) { clockMs += ms; }
inline unsigned long millis() { return clockMs; }
constexpr int INPUT_PULLUP=2, OUTPUT=3, LOW=0, HIGH=1;
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
inline void delayMicroseconds(unsigned long) {}
