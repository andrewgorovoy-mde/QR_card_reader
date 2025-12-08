#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

const int BUTTON_RIVER_PIN = A0;
const int BUTTON_HAND_PIN  = A1;
const int LED_PIN = LED_BUILTIN;

int lastRiverButtonState = HIGH;
int lastHandButtonState  = HIGH;

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);

const int SERVOMIN = 150;
const int SERVOMAX = 600;

const int CH_CARD1_SUIT   = 0;
const int CH_CARD1_VALUE1 = 1;
const int CH_CARD1_VALUE2 = 2;
const int CH_CARD2_SUIT   = 3;
const int CH_CARD2_VALUE1 = 4;
const int CH_CARD2_VALUE2 = 5;

const float CH0_POS[8] = {2.50, 27, 51.429, 77.143, 102.857, 118.00, 140, 158};
const float CH1_POS[8] = {5, 27, 51.429, 77.143, 105, 121.00, 140, 158};
const float CH2_POS[8] = {12, 30, 51.429, 81, 102.857, 118.00, 140, 158};
const float CH3_POS[8] = {2.50, 27, 51.429, 77.143, 102.857, 118.00, 140, 158};
const float CH4_POS[8] = {5, 27, 51.429, 81, 102.857, 121.00, 140, 158};
const float CH5_POS[8] = {12, 30, 51.429, 77.143, 102.857, 118.00, 140, 158};

const float* getChannelPos(int ch) {
  if (ch == 0) return CH0_POS;
  if (ch == 1) return CH1_POS;
  if (ch == 2) return CH2_POS;
  if (ch == 3) return CH3_POS;
  if (ch == 4) return CH4_POS;
  if (ch == 5) return CH5_POS;
  return CH0_POS;
}

void writeServoAngle(int channel, float angle) {
  if (angle < 0) angle = 0;
  if (angle > 180) angle = 180;
  pwm.setPWM(channel, 0, map((int)angle, 0, 180, SERVOMIN, SERVOMAX));
}

void moveSuit(int channel, char label) {
  label = toupper(label);
  const float* pos = getChannelPos(channel);
  float angle = -1;
  if (label == 'H') angle = pos[6];
  else if (label == 'D') angle = pos[5];
  else if (label == 'B') angle = pos[3];
  else if (label == 'C') angle = pos[2];
  else if (label == 'S') angle = pos[1];
  if (angle >= 0) writeServoAngle(channel, angle);
}

void moveValue1(int channel, char label) {
  label = toupper(label);
  const float* pos = getChannelPos(channel);
  float angle = -1;
  if (label == '2') angle = pos[6];
  else if (label == '3') angle = pos[5];
  else if (label == '4') angle = pos[4];
  else if (label == 'B') angle = pos[3];
  else if (label == '5') angle = pos[2];
  else if (label == '6') angle = pos[1];
  else if (label == '7') angle = pos[0];
  if (angle >= 0) writeServoAngle(channel, angle);
}

void moveValue2(int channel, char label) {
  label = toupper(label);
  const float* pos = getChannelPos(channel);
  float angle = -1;
  if (label == '8') angle = pos[0];
  else if (label == '9') angle = pos[1];
  else if (label == '1') angle = pos[2];
  else if (label == 'B') angle = pos[3];
  else if (label == 'J') angle = pos[4];
  else if (label == 'Q') angle = pos[5];
  else if (label == 'K') angle = pos[6];
  else if (label == 'A') angle = pos[7];
  if (angle >= 0) writeServoAngle(channel, angle);
}

void resetAllServos() {
  writeServoAngle(CH_CARD1_SUIT, getChannelPos(0)[3]);
  writeServoAngle(CH_CARD1_VALUE1, getChannelPos(1)[3]);
  writeServoAngle(CH_CARD1_VALUE2, getChannelPos(2)[3]);
  writeServoAngle(CH_CARD2_SUIT, getChannelPos(3)[3]);
  writeServoAngle(CH_CARD2_VALUE1, getChannelPos(4)[3]);
  writeServoAngle(CH_CARD2_VALUE2, getChannelPos(5)[3]);
}

void flashLed(int times, int onMs, int offMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(onMs);
    digitalWrite(LED_PIN, LOW);
    delay(offMs);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_RIVER_PIN, INPUT_PULLUP);
  pinMode(BUTTON_HAND_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  pwm.begin();
  pwm.setPWMFreq(50);
  delay(10);
  resetAllServos();
}

void loop() {
  int riverState = digitalRead(BUTTON_RIVER_PIN);
  if (lastRiverButtonState == HIGH && riverState == LOW) {
    Serial.println("RIVER");
    flashLed(1, 80, 80);
  }
  lastRiverButtonState = riverState;

  int handState = digitalRead(BUTTON_HAND_PIN);
  if (lastHandButtonState == HIGH && handState == LOW) {
    Serial.println("HAND");
    flashLed(1, 80, 80);
  }
  lastHandButtonState = handState;

  if (Serial.available() > 0) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) return;

    if (line == "RESET" || line == "reset") {
      resetAllServos();
      return;
    }

    if (line.startsWith("HAND:")) {
      String payload = line.substring(5);
      payload.trim();
      String parts[6];
      int partIndex = 0;
      int start = 0;

      while (partIndex < 6) {
        int commaIndex = payload.indexOf(',', start);
        if (commaIndex == -1) {
          parts[partIndex] = payload.substring(start);
          parts[partIndex].trim();
          partIndex++;
          break;
        } else {
          parts[partIndex] = payload.substring(start, commaIndex);
          parts[partIndex].trim();
          partIndex++;
          start = commaIndex + 1;
        }
      }

      if (partIndex == 6) {
        char s1 = parts[0].charAt(0);
        char v1_1 = parts[1].charAt(0);
        char v1_2 = (parts[2] == "10") ? '1' : parts[2].charAt(0);
        
        char s2 = parts[3].charAt(0);
        char v2_1 = parts[4].charAt(0);
        char v2_2 = (parts[5] == "10") ? '1' : parts[5].charAt(0);

        moveSuit(CH_CARD1_SUIT, s1);
        moveValue1(CH_CARD1_VALUE1, v1_1);
        moveValue2(CH_CARD1_VALUE2, v1_2);
        moveSuit(CH_CARD2_SUIT, s2);
        moveValue1(CH_CARD2_VALUE1, v2_1);
        moveValue2(CH_CARD2_VALUE2, v2_2);
      }
      return;
    }

    int spaceIndex = line.indexOf(' ');
    if (spaceIndex == -1) return;

    String name = line.substring(0, spaceIndex);
    String value = line.substring(spaceIndex + 1);
    name.trim();
    value.trim();
    char val = value.charAt(0);

    if (name == "card1suit") moveSuit(CH_CARD1_SUIT, val);
    else if (name == "card1value1") moveValue1(CH_CARD1_VALUE1, val);
    else if (name == "card1value2") {
      if (value == "10") moveValue2(CH_CARD1_VALUE2, '1');
      else moveValue2(CH_CARD1_VALUE2, val);
    }
    else if (name == "card2suit") moveSuit(CH_CARD2_SUIT, val);
    else if (name == "card2value1") moveValue1(CH_CARD2_VALUE1, val);
    else if (name == "card2value2") {
      if (value == "10") moveValue2(CH_CARD2_VALUE2, '1');
      else moveValue2(CH_CARD2_VALUE2, val);
    }
  }
}
