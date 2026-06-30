#include <Wire.h>
#include "Adafruit_VL53L1X.h"

Adafruit_VL53L1X tof = Adafruit_VL53L1X();

// LRA driver pins - 8 GPIO for 4 motors with bidirectional control
// Motor 1: LEFT motion
int LRA1_IN_PLUS = 18;
int LRA1_IN_MINUS = 5;

// Motor 2: RIGHT motion
int LRA2_IN_PLUS = 19;
int LRA2_IN_MINUS = 33;

// Motor 3: APPROACHING
int LRA3_IN_PLUS = 25;
int LRA3_IN_MINUS = 32;

// Motor 4: GOING AWAY
int LRA4_IN_PLUS = 26;
int LRA4_IN_MINUS = 14;

// RCWL-0516 motion sensor pin
int MOTION_SENSOR = 27;

int prevDistance = -1;
bool systemActive = false;
bool motionDetected = false;

// LRA state tracking
bool lra1_active = false;
bool lra2_active = false;
bool lra3_active = false;
bool lra4_active = false;

// Timing for vibration pulses (only for camera-based left/right)
unsigned long lra1_start = 0;
unsigned long lra2_start = 0;
const unsigned long PULSE_DURATION = 150; // ms

// TOF reading timing
unsigned long lastTofRead = 0;
const unsigned long TOF_INTERVAL = 300; // Read TOF every 300ms

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  // Setup motion sensor
  pinMode(MOTION_SENSOR, INPUT);
  
  // Setup LRA pins
  pinMode(LRA1_IN_PLUS, OUTPUT);
  pinMode(LRA1_IN_MINUS, OUTPUT);
  pinMode(LRA2_IN_PLUS, OUTPUT);
  pinMode(LRA2_IN_MINUS, OUTPUT);
  pinMode(LRA3_IN_PLUS, OUTPUT);
  pinMode(LRA3_IN_MINUS, OUTPUT);
  pinMode(LRA4_IN_PLUS, OUTPUT);
  pinMode(LRA4_IN_MINUS, OUTPUT);
  
  // All LRAs off initially
  stopMotor(1);
  stopMotor(2);
  stopMotor(3);
  stopMotor(4);
  
  // Setup I2C for TOF
  Wire.begin(21, 22);
  Wire.setClock(100000);
  
  // Initialize TOF sensor
  if (!tof.begin()) {
    Serial.println("Failed to init VL53L1X");
    while (1);
  }
  
  Serial.println(" System Initialized");
  Serial.println("⏸  Waiting for motion...");
}

void controlLRA(int motorNum, int direction, int strength) {
  strength = constrain(strength, 0, 200);
  int pinPlus, pinMinus;
  bool *activeFlag;
  
  if (motorNum == 1) {
    pinPlus = LRA1_IN_PLUS;
    pinMinus = LRA1_IN_MINUS;
    activeFlag = &lra1_active;
  } else if (motorNum == 2) {
    pinPlus = LRA2_IN_PLUS;
    pinMinus = LRA2_IN_MINUS;
    activeFlag = &lra2_active;
  } else if (motorNum == 3) {
    pinPlus = LRA3_IN_PLUS;
    pinMinus = LRA3_IN_MINUS;
    activeFlag = &lra3_active;
  } else if (motorNum == 4) {
    pinPlus = LRA4_IN_PLUS;
    pinMinus = LRA4_IN_MINUS;
    activeFlag = &lra4_active;
  } else {
    return;
  }
  
  if (direction == 1) {
    analogWrite(pinPlus, strength);
    analogWrite(pinMinus, 0);
    *activeFlag = true;
  } else if (direction == -1) {
    analogWrite(pinPlus, 0);
    analogWrite(pinMinus, strength);
    *activeFlag = true;
  } else {
    analogWrite(pinPlus, 0);
    analogWrite(pinMinus, 0);
    *activeFlag = false;
  }
}

void stopMotor(int motorNum) {
  controlLRA(motorNum, 0, 0);
}

void processTOFDistance() {
  if (!systemActive) return;
  
  unsigned long currentTime = millis();
  
  // Only read TOF at specified intervals
  if (currentTime - lastTofRead < TOF_INTERVAL) {
    return;
  }
  
  lastTofRead = currentTime;
  
  int distance = tof.distance();
  
  if (distance == -1) {
    Serial.println("  ToF error");
    return;
  }
  
  Serial.print(" Distance: ");
  Serial.print(distance);
  Serial.println(" mm");
  
  if (prevDistance != -1) {
    int diff = distance - prevDistance;
    
    // Threshold: 100mm (10cm)
    if (diff < -100) {
      // APPROACHING - continuous vibration
      Serial.println("   Approaching → LRA3 ON");
      controlLRA(3, 1, 120);
      controlLRA(4, 0, 0);
    } else if (diff > 100) {
      // GOING AWAY - continuous vibration
      Serial.println("    Going away → LRA4 ON");
      controlLRA(3, 0, 0);
      controlLRA(4, 1, 120);
    } else {
      // Stationary - turn off both
      Serial.println("    Stationary → LRA3/4 OFF");
      controlLRA(3, 0, 0);
      controlLRA(4, 0, 0);
    }
  }
  
  prevDistance = distance;
}

void checkMotion() {
  bool currentMotion = digitalRead(MOTION_SENSOR);
  
  if (currentMotion && !motionDetected) {
    motionDetected = true;
    systemActive = true;
    
    Serial.println("\n MOTION DETECTED!");
    Serial.println("✅ System ACTIVATED");
    Serial.println("==================================================");
    
    tof.startRanging();
    prevDistance = -1;
    lastTofRead = 0;
  } else if (!currentMotion && motionDetected) {
    motionDetected = false;
    systemActive = false;
    
    Serial.println("\n  Motion stopped - System DEACTIVATED");
    Serial.println("==================================================\n");
    
    // Turn off all LRAs
    stopMotor(1);
    stopMotor(2);
    stopMotor(3);
    stopMotor(4);
    lra1_start = 0;
    lra2_start = 0;
  }
}

// NON-BLOCKING pulse management for camera-based left/right only
void managePulses() {
  unsigned long now = millis();
  
  if (lra1_active && lra1_start > 0 && (now - lra1_start >= PULSE_DURATION)) {
    stopMotor(1);
    lra1_start = 0;
  }
  
  if (lra2_active && lra2_start > 0 && (now - lra2_start >= PULSE_DURATION)) {
    stopMotor(2);
    lra2_start = 0;
  }
}

void loop() {
  // ALWAYS check motion sensor
  checkMotion();
  
  // Manage camera-based left/right pulses
  managePulses();
  
  if (systemActive) {
    // Process TOF for approaching/going away (LRA3/4)
    processTOFDistance();
    
    // Check for camera commands (LEFT/RIGHT only - LRA1/2)
    if (Serial.available() > 0) {
      String command = Serial.readStringUntil('\n');
      command.trim();
      command.toLowerCase();
      
      if (command == "lra1") {
        Serial.println(" LRA1 (LEFT) PULSE");
        controlLRA(1, 1, 150);
        lra1_start = millis();
        
      } else if (command == "lra2") {
        Serial.println(" LRA2 (RIGHT) PULSE");
        controlLRA(2, 1, 150);
        lra2_start = millis();

      } else if (command == "off_lra1") {
        stopMotor(1);
        lra1_start = 0;
        
      } else if (command == "off_lra2") {
        stopMotor(2);
        lra2_start = 0;
        
      } else if (command == "off") {
        Serial.println("  All LRAs OFF");
        stopMotor(1);
        stopMotor(2);
        stopMotor(3);
        stopMotor(4);
        lra1_start = lra2_start = 0;
      }
    }
    
    delay(50);  // Fast loop when active
  } else {
    // Idle - check for manual override
    if (Serial.available() > 0) {
      String command = Serial.readStringUntil('\n');
      command.trim();
      if (command == "force_start") {
        systemActive = true;
        motionDetected = true;
        Serial.println("✅ System FORCE ACTIVATED");
        tof.startRanging();
        prevDistance = -1;
        lastTofRead = 0;
      }
    }
    
    delay(50);
  }
}