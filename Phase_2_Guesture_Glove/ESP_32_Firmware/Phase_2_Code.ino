#include <Wire.h>
#include <BluetoothSerial.h>
#include <Preferences.h>
#include <math.h>

// =====================================================
// BLUETOOTH
// =====================================================

BluetoothSerial SerialBT;

// =====================================================
// STORAGE
// =====================================================

Preferences prefs;

// =====================================================
// FLEX SENSOR PINS
// =====================================================

const int thumbPin = 34;
const int indexPin = 35;

// =====================================================
// FLEX DIRECTION
// true  = opposite mounted sensors
// false = normal mounted sensors
// =====================================================

const bool invertFlex = true;

// =====================================================
// MPU6050
// =====================================================

const int MPU_ADDR = 0x68;

int16_t AcX, AcY, AcZ;

float gForceX, gForceY, gForceZ;
float pitch, roll;

// =====================================================
// THRESHOLDS
// =====================================================

int thumbThreshold;
int indexThreshold;

int pitchThreshold;
int rollThreshold;

// =====================================================
// MPU NEUTRAL VALUES
// =====================================================

float neutralPitch;
float neutralRoll;

// =====================================================
// SENSOR VALUES
// =====================================================

int thumbValue;
int indexValue;

// =====================================================
// ANTI-SPAM CONTROL
// =====================================================

String lastGesture = "";

unsigned long lastSendTime = 0;

const int sendInterval = 2200;

// =====================================================
// SETUP
// =====================================================

void setup()
{
  Serial.begin(115200);

  // Bluetooth Name
  SerialBT.begin("GestureGlove_Pro");

  // Preferences
  prefs.begin("gesture", false);

  // Load saved values
  thumbThreshold =
    prefs.getInt("thumb", 2200);

  indexThreshold =
    prefs.getInt("index", 2200);

  pitchThreshold =
    prefs.getInt("pitch", 20);

  rollThreshold =
    prefs.getInt("roll", 20);

  neutralPitch =
    prefs.getFloat("nPitch", 0);

  neutralRoll =
    prefs.getFloat("nRoll", 0);

  // MPU6050 Setup
  Wire.begin(21, 22);

  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);
  Wire.write(0);
  Wire.endTransmission(true);

  Serial.println("================================");
  Serial.println("Gesture Glove Started");
  Serial.println("Bluetooth Ready");
  Serial.println("================================");
}

// =====================================================
// LOOP
// =====================================================

void loop()
{
  readSensors();

  handleBluetooth();

  String currentGesture =
    detectGestureLogic();

  // ==========================================
  // SEND ONLY NEW GESTURES
  // ==========================================

  if (currentGesture != "" &&
      currentGesture != lastGesture &&
      (millis() - lastSendTime >
       sendInterval))
  {
    Serial.println("================================");

    Serial.print("Thumb: ");
    Serial.println(thumbValue);

    Serial.print("Index: ");
    Serial.println(indexValue);

    Serial.print("Pitch: ");
    Serial.println(pitch);

    Serial.print("Roll: ");
    Serial.println(roll);

    Serial.print("Gesture: ");
    Serial.println(currentGesture);

    Serial.println("================================");

    SerialBT.println(
      "" + currentGesture);

    lastGesture = currentGesture;

    lastSendTime = millis();
  }

  else if (currentGesture == "")
  {
    lastGesture = "";
  }

  // ==========================================
  // SERIAL DEBUG SPEECH
  // ==========================================

  if (Serial.available())
  {
    String debugText =
      Serial.readStringUntil('\n');

    debugText.trim();

    if (debugText.length() > 0)
    {
      SerialBT.println(
        "" + debugText);

      Serial.println(
        "Sent To Phone: " + debugText);
    }
  }

  delay(50);
}

// =====================================================
// READ SENSORS
// =====================================================

void readSensors()
{
  // FLEX SENSORS
  thumbValue = analogRead(thumbPin);
  indexValue = analogRead(indexPin);

  // MPU6050
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  Wire.endTransmission(false);

  Wire.requestFrom(MPU_ADDR, 6, true);

  AcX = Wire.read() << 8 | Wire.read();
  AcY = Wire.read() << 8 | Wire.read();
  AcZ = Wire.read() << 8 | Wire.read();

  // Convert to G force
  gForceX = AcX / 16384.0;
  gForceY = AcY / 16384.0;
  gForceZ = AcZ / 16384.0;

  // Calculate pitch
  pitch = atan2(
            gForceY,
            sqrt(pow(gForceX, 2) +
                 pow(gForceZ, 2))
          ) * 180 / PI;

  // Calculate roll
  roll = atan2(
           -gForceX,
           sqrt(pow(gForceY, 2) +
                pow(gForceZ, 2))
         ) * 180 / PI;
}

// =====================================================
// FINAL DEMO GESTURE LOGIC
// =====================================================

String detectGestureLogic()
{
  bool thumbBent =
    invertFlex ?
    thumbValue < thumbThreshold :
    thumbValue > thumbThreshold;

  bool indexBent =
    invertFlex ?
    indexValue < indexThreshold :
    indexValue > indexThreshold;

  bool up =
    (pitch - neutralPitch) > pitchThreshold;

  bool down =
    (pitch - neutralPitch) < -pitchThreshold;

  // ==========================================
  // PRIORITY 1 : HELP
  // BOTH FINGERS CLOSED
  // ==========================================

  if (thumbBent &&
      indexBent)
  {
    return "Help";
  }

  // ==========================================
  // PROFESSOR DEMO QUESTION
  // THUMB OPEN + INDEX BENT
  // ==========================================

  if (!thumbBent &&
      indexBent &&
      !up &&
      !down)
  {
    return "Professors, did you like the demo?";
  }

  // ==========================================
  // THUMB ONLY
  // ==========================================

  if (thumbBent &&
      !indexBent &&
      !up &&
      !down)
  {
    return "Hi, my name is xyz.";
  }

  // ==========================================
  // UP GESTURES
  // ==========================================

  if (up &&
      !thumbBent &&
      !indexBent)
  {
    return "Please give me water.";
  }

  if (up &&
      thumbBent &&
      !indexBent)
  {
    return "What is in dinner today?";
  }

  // ==========================================
  // DOWN GESTURES
  // ==========================================

  if (down &&
      !thumbBent &&
      !indexBent)
  {
    return "Please move aside.";
  }

  if (down &&
      thumbBent &&
      !indexBent)
  {
    return "Call this number 9XX9.";
  }

  // ==========================================
  // EXTRA GESTURE
  // ==========================================

  if (up &&
      indexBent)
  {
    return "Thank you.";
  }

  return "";
}

// =====================================================
// HANDLE BLUETOOTH
// =====================================================

void handleBluetooth()
{
  if (!SerialBT.available())
    return;

  String incoming =
    SerialBT.readStringUntil('\n');

  incoming.trim();

  Serial.print("Received: ");
  Serial.println(incoming);

  // ==========================================
  // SMART CALIBRATION
  // ==========================================

  if (incoming == "CALIBRATE")
  {
    calibrateSensors();
  }

  // ==========================================
  // MANUAL SETTINGS
  // ==========================================

  else if (incoming.startsWith("SET:"))
  {
    parseThresholds(incoming);
  }
}

// =====================================================
// MANUAL THRESHOLD SETTINGS
// =====================================================

void parseThresholds(String data)
{
  data.remove(0, 4);

  int first =
    data.indexOf(',');

  int second =
    data.indexOf(',', first + 1);

  int third =
    data.indexOf(',', second + 1);

  thumbThreshold =
    data.substring(0, first).toInt();

  indexThreshold =
    data.substring(first + 1,
                   second).toInt();

  pitchThreshold =
    data.substring(second + 1,
                   third).toInt();

  rollThreshold =
    data.substring(third + 1).toInt();

  // Save permanently
  prefs.putInt("thumb",
               thumbThreshold);

  prefs.putInt("index",
               indexThreshold);

  prefs.putInt("pitch",
               pitchThreshold);

  prefs.putInt("roll",
               rollThreshold);

  Serial.println(
    "Thresholds Updated");

  SerialBT.println(
    "NOTIFY:Thresholds Saved");
}

// =====================================================
// SMART CALIBRATION
// =====================================================

void calibrateSensors()
{
  Serial.println("================================");
  Serial.println("Smart Calibration Started");

  // ==========================================
  // STEP 1 : NEUTRAL POSITION
  // ==========================================

  SerialBT.println("NOTIFY:Keep hand straight");
  Serial.println("Keep hand straight");

  delay(4000);

  readSensors();

  neutralPitch = pitch;
  neutralRoll  = roll;

  // ==========================================
  // STEP 2 : FLEX OPEN
  // ==========================================

  int thumbOpen = analogRead(thumbPin);
  int indexOpen = analogRead(indexPin);

  // ==========================================
  // STEP 3 : FLEX CLOSED
  // ==========================================

  SerialBT.println("NOTIFY:Bend fingers now");
  Serial.println("Bend fingers now");

  delay(4000);

  int thumbBent = analogRead(thumbPin);
  int indexBent = analogRead(indexPin);

  thumbThreshold =
    (thumbOpen + thumbBent) / 2;

  indexThreshold =
    (indexOpen + indexBent) / 2;

  // ==========================================
  // STEP 4 : ROLL CALIBRATION
  // ==========================================

  SerialBT.println("NOTIFY:Tilt RIGHT now");
  Serial.println("Tilt RIGHT now");

  delay(4000);

  readSensors();

  rollThreshold =
    abs(roll - neutralRoll) * 0.7;

  // ==========================================
  // STEP 5 : PITCH CALIBRATION
  // ==========================================

  SerialBT.println("NOTIFY:Tilt UP now");
  Serial.println("Tilt UP now");

  delay(4000);

  readSensors();

  pitchThreshold =
    abs(pitch - neutralPitch) * 1.2;

  // Minimum safety values
  if (pitchThreshold < 10)
    pitchThreshold = 10;

  if (rollThreshold < 10)
    rollThreshold = 10;

  // ==========================================
  // SAVE EVERYTHING
  // ==========================================

  prefs.putInt("thumb", thumbThreshold);
  prefs.putInt("index", indexThreshold);

  prefs.putInt("pitch", pitchThreshold);
  prefs.putInt("roll", rollThreshold);

  prefs.putFloat("nPitch", neutralPitch);
  prefs.putFloat("nRoll", neutralRoll);

  // ==========================================
  // DEBUG
  // ==========================================

  Serial.println("================================");

  Serial.print("Thumb Threshold: ");
  Serial.println(thumbThreshold);

  Serial.print("Index Threshold: ");
  Serial.println(indexThreshold);

  Serial.print("Pitch Threshold: ");
  Serial.println(pitchThreshold);

  Serial.print("Roll Threshold: ");
  Serial.println(rollThreshold);

  Serial.println("Calibration Complete");
  Serial.println("================================");

  SerialBT.println("NOTIFY:Calibration Done");
}