import time
import math
import IMU
import datetime
import csv
import os
from bmp388 import BMP388
import serial
from adxl345 import ADXL345
  


#!/usr/bin/python

# This is the base code needed to get usable angles from the IMU on
# the OzzMaker SARA-R5 LTE-M GPS + 10DOF board using a Complementary filter.
#
# This program includes two filters (low pass and median) to improve the
# values returned from the IMU by reducing noise.
 

RAD_TO_DEG = 57.29578
M_PI = 3.14159265358979323846
G_GAIN = 0.070  # [deg/s/LSB] If you change the dps for gyro, you need to update this value accordingly
AA = 0.40  # Complementary filter constant
MAG_LPF_FACTOR = 0.4  # Low pass filter constant magnetometer
ACC_LPF_FACTOR = 0.4  # Low pass filter constant for accelerometer
ACC_MEDIANTABLESIZE = 9  # Median filter table size for accelerometer. Higher = smoother but a longer delay
MAG_MEDIANTABLESIZE = 9  # Median filter table size for magnetometer. Higher = smoother but a longer delay

################# Compass Calibration values ############
# Use calibrateBerryIMU.py to get calibration values
# Calibrating the compass isnt mandatory, however a calibrated
# compass will result in a more accurate heading value.
with open('magnetometer_values.txt', 'r') as file:
    calibration_values = file.read().splitlines()

magXmin, magYmin, magZmin, magXmax, magYmax, magZmax = map(int, calibration_values)

############### END Calibration offsets #################

# Kalman filter variables
Q_angle = 0.02
Q_gyro = 0.0015
R_angle = 0.005
y_bias = 0.0
x_bias = 0.0
XP_00 = 0.0
XP_01 = 0.0
XP_10 = 0.0
XP_11 = 0.0
YP_00 = 0.0
YP_01 = 0.0
YP_10 = 0.0
YP_11 = 0.0
KFangleX = 0.0
KFangleY = 0.0
stop_flag = False


def initialize_serial(port, baud_rate):
    try:
        ser = serial.Serial(port, baud_rate)
        return ser
    except:
        print("Device Not detected.")
        return None

def kalmanFilterY(accAngle, gyroRate, DT):
    """
    Applies the Kalman filter to estimate the angle in the Y-axis based on accelerometer and gyroscope measurements.

    Parameters:
    - accAngle (float): The angle measured by the accelerometer in the Y-axis.
    - gyroRate (float): The rate of change of the gyroscope in the Y-axis.
    - DT (float): The time interval between measurements.

    Returns:
    - KFangleY (float): The estimated angle in the Y-axis after applying the Kalman filter.
    """
    y = 0.0
    S = 0.0

    global KFangleY
    global Q_angle
    global Q_gyro
    global y_bias
    global YP_00
    global YP_01
    global YP_10
    global YP_11

    KFangleY = KFangleY + DT * (gyroRate - y_bias)

    YP_00 = YP_00 + (-DT * (YP_10 + YP_01) + Q_angle * DT)
    YP_01 = YP_01 + (-DT * YP_11)
    YP_10 = YP_10 + (-DT * YP_11)
    YP_11 = YP_11 + (+Q_gyro * DT)

    y = accAngle - KFangleY
    S = YP_00 + R_angle
    K_0 = YP_00 / S
    K_1 = YP_10 / S

    KFangleY = KFangleY + (K_0 * y)
    y_bias = y_bias + (K_1 * y)

    YP_00 = YP_00 - (K_0 * YP_00)
    YP_01 = YP_01 - (K_0 * YP_01)
    YP_10 = YP_10 - (K_1 * YP_00)
    YP_11 = YP_11 - (K_1 * YP_01)

    return KFangleY


def kalmanFilterX(accAngle, gyroRate, DT):
    """
    Applies the Kalman filter to estimate the angle in the X-axis based on accelerometer and gyroscope measurements.

    Parameters:
    - accAngle (float): The angle measured by the accelerometer in the X-axis.
    - gyroRate (float): The rate of change of the gyroscope in the X-axis.
    - DT (float): The time interval between measurements.

    Returns:
    - KFangleY (float): The estimated angle in the X-axis after applying the Kalman filter.
    """
    x = 0.0
    S = 0.0

    global KFangleX
    global Q_angle
    global Q_gyro
    global x_bias
    global XP_00
    global XP_01
    global XP_10
    global XP_11

    KFangleX = KFangleX + DT * (gyroRate - x_bias)

    XP_00 = XP_00 + (-DT * (XP_10 + XP_01) + Q_angle * DT)
    XP_01 = XP_01 + (-DT * XP_11)
    XP_10 = XP_10 + (-DT * XP_11)
    XP_11 = XP_11 + (+Q_gyro * DT)

    x = accAngle - KFangleX
    S = XP_00 + R_angle
    K_0 = XP_00 / S
    K_1 = XP_10 / S

    KFangleX = KFangleX + (K_0 * x)
    x_bias = x_bias + (K_1 * x)

    XP_00 = XP_00 - (K_0 * XP_00)
    XP_01 = XP_01 - (K_0 * XP_01)
    XP_10 = XP_10 - (K_1 * XP_00)
    XP_11 = XP_11 - (K_1 * XP_01)

    return KFangleX


gyroXangle = 0.0
gyroYangle = 0.0
gyroZangle = 0.0
CFangleX = 0.0
CFangleY = 0.0
CFangleXFiltered = 0.0
CFangleYFiltered = 0.0
kalmanX = 0.0
kalmanY = 0.0
oldXMagRawValue = 0
oldYMagRawValue = 0
oldZMagRawValue = 0
oldXAccRawValue = 0
oldYAccRawValue = 0
oldZAccRawValue = 0

a = datetime.datetime.now()

# Setup the tables for the median filter. Fill them all with '1' so we dont get divide by zero error
acc_medianTable1X = [1] * ACC_MEDIANTABLESIZE
acc_medianTable1Y = [1] * ACC_MEDIANTABLESIZE
acc_medianTable1Z = [1] * ACC_MEDIANTABLESIZE
acc_medianTable2X = [1] * ACC_MEDIANTABLESIZE
acc_medianTable2Y = [1] * ACC_MEDIANTABLESIZE
acc_medianTable2Z = [1] * ACC_MEDIANTABLESIZE
mag_medianTable1X = [1] * MAG_MEDIANTABLESIZE
mag_medianTable1Y = [1] * MAG_MEDIANTABLESIZE
mag_medianTable1Z = [1] * MAG_MEDIANTABLESIZE
mag_medianTable2X = [1] * MAG_MEDIANTABLESIZE
mag_medianTable2Y = [1] * MAG_MEDIANTABLESIZE
mag_medianTable2Z = [1] * MAG_MEDIANTABLESIZE

IMU.detectIMU()  # Detect if BerryIMU is connected.

IMU.initIMU()  # Initialise the accelerometer, gyroscope and compass
 #Initalise Pessure

bmp388 = BMP388();
adxl345 = ADXL345();
counter = 0;

while os.path.exists(f'/mnt/usb/DATA_{counter}.csv'):
    counter += 1

filename = f'/mnt/usb/DATA_{counter}.csv'

with open(filename, 'w') as data_:
    data_writer = csv.writer(data_)
    date = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
    data_writer.writerow(["X (DEG)", "Y (DEG)", "X (G)", "Y (G)", "Z (G)", "PRESSURE (ATM)", "TEMP (C)", "ALT (M)", "HEADING (DEG)", "TIME (S)", ("START: " + date)])
    elasped_time = 0;
    radio = initialize_serial("/dev/ttyUSB0", 115200)
    while True:
        if stop_flag is True:
            exit(0)
        brainACC = adxl345.getAxes(True)
        start_time = time.time()        # Read the accelerometer, gyroscope and magnetometer values
        ACCx = IMU.readACCx()
        ACCy = IMU.readACCy()
        ACCz = IMU.readACCz()
        GYRx = IMU.readGYRx()
        GYRy = IMU.readGYRy()
        GYRz = IMU.readGYRz()
        MAGx = IMU.readMAGx()
        MAGy = IMU.readMAGy()
        MAGz = IMU.readMAGz()

        ACCGx = ACCx
        ACCGy = ACCy
        ACCGz = ACCz

        # Apply compass calibration
        MAGx -= (magXmin + magXmax) / 2
        MAGy -= (magYmin + magYmax) / 2
        MAGz -= (magZmin + magZmax) / 2

        # Times raw mag by sensitivity
        MAGx = MAGx * (1.0 / 16384.0)  # 18 bits
        MAGy = MAGy * (1.0 / 16384.0)  # 18 bits
        MAGz = MAGz * (1.0 / 16384.0)  # 18 bits

        ##Calculate loop Period(LP). How long between Gyro Reads
        b = datetime.datetime.now() - a
        a = datetime.datetime.now()
        LP = b.microseconds / (1000000 * 1.0)
        outputString = "Loop Time %5.2f " % (LP)

        ###############################################
        #### Apply low pass filter ####
        ###############################################
        MAGx = MAGx * MAG_LPF_FACTOR + oldXMagRawValue * (1 - MAG_LPF_FACTOR)
        MAGy = MAGy * MAG_LPF_FACTOR + oldYMagRawValue * (1 - MAG_LPF_FACTOR)
        MAGz = MAGz * MAG_LPF_FACTOR + oldZMagRawValue * (1 - MAG_LPF_FACTOR)
        ACCx = ACCx * ACC_LPF_FACTOR + oldXAccRawValue * (1 - ACC_LPF_FACTOR)
        ACCy = ACCy * ACC_LPF_FACTOR + oldYAccRawValue * (1 - ACC_LPF_FACTOR)
        ACCz = ACCz * ACC_LPF_FACTOR + oldZAccRawValue * (1 - ACC_LPF_FACTOR)

        oldXMagRawValue = MAGx
        oldYMagRawValue = MAGy
        oldZMagRawValue = MAGz
        oldXAccRawValue = ACCx
        oldYAccRawValue = ACCy
        oldZAccRawValue = ACCz

        #########################################
        #### Median filter for accelerometer ####
        #########################################
        # cycle the table
        for x in range(ACC_MEDIANTABLESIZE - 1, 0, -1):
            acc_medianTable1X[x] = acc_medianTable1X[x - 1]
            acc_medianTable1Y[x] = acc_medianTable1Y[x - 1]
            acc_medianTable1Z[x] = acc_medianTable1Z[x - 1]

        # Insert the latest values
        acc_medianTable1X[0] = ACCx # type: ignore
        acc_medianTable1Y[0] = ACCy # type: ignore
        acc_medianTable1Z[0] = ACCz # type: ignore

        # Copy the tables
        acc_medianTable2X = acc_medianTable1X[:]
        acc_medianTable2Y = acc_medianTable1Y[:]
        acc_medianTable2Z = acc_medianTable1Z[:]

        # Sort table 2
        acc_medianTable2X.sort()
        acc_medianTable2Y.sort()
        acc_medianTable2Z.sort()

        # The middle value is the value we are interested in
        ACCx = acc_medianTable2X[int(ACC_MEDIANTABLESIZE / 2)]
        ACCy = acc_medianTable2Y[int(ACC_MEDIANTABLESIZE / 2)]
        ACCz = acc_medianTable2Z[int(ACC_MEDIANTABLESIZE / 2)]

        #########################################
        #### Median filter for magnetometer ####
        #########################################
        # cycle the table
        for x in range(MAG_MEDIANTABLESIZE - 1, 0, -1):
            mag_medianTable1X[x] = mag_medianTable1X[x - 1]
            mag_medianTable1Y[x] = mag_medianTable1Y[x - 1]
            mag_medianTable1Z[x] = mag_medianTable1Z[x - 1]

        # Insert the latest values
        mag_medianTable1X[0] = MAGx # type: ignore
        mag_medianTable1Y[0] = MAGy # type: ignore
        mag_medianTable1Z[0] = MAGz # type: ignore

        # Copy the tables
        mag_medianTable2X = mag_medianTable1X[:]
        mag_medianTable2Y = mag_medianTable1Y[:]
        mag_medianTable2Z = mag_medianTable1Z[:]

        # Sort table 2
        mag_medianTable2X.sort()
        mag_medianTable2Y.sort()
        mag_medianTable2Z.sort()

        # The middle value is the value we are interested in
        MAGx = mag_medianTable2X[int(MAG_MEDIANTABLESIZE / 2)]
        MAGy = mag_medianTable2Y[int(MAG_MEDIANTABLESIZE / 2)]
        MAGz = mag_medianTable2Z[int(MAG_MEDIANTABLESIZE / 2)]

        # Convert Gyro raw to degrees per second
        rate_gyr_x = GYRx * G_GAIN
        rate_gyr_y = GYRy * G_GAIN
        rate_gyr_z = GYRz * G_GAIN

        # Calculate the angles from the gyro.
        gyroXangle += rate_gyr_x * LP
        gyroYangle += rate_gyr_y * LP
        gyroZangle += rate_gyr_z * LP

        # Convert Accelerometer values to degrees
        AccXangle = (math.atan2(ACCy, ACCz) * RAD_TO_DEG)
        AccYangle = (math.atan2(ACCz, ACCx) + M_PI) * RAD_TO_DEG

        # Change the rotation value of the accelerometer to -/+ 180 and
        # move the Y axis '0' point to up. This makes it easier to read.
        if AccYangle > 90:
            AccYangle -= 270.0
        else:
            AccYangle += 90.0

        # Complementary filter used to combine the accelerometer and gyro values.
        CFangleX = AA * (CFangleX + rate_gyr_x * LP) + (1 - AA) * AccXangle
        CFangleY = AA * (CFangleY + rate_gyr_y * LP) + (1 - AA) * AccYangle

        # Kalman filter used to combine the accelerometer and gyro values.
        kalmanY = kalmanFilterY(AccYangle, rate_gyr_y, LP)
        kalmanX = kalmanFilterX(AccXangle, rate_gyr_x, LP)

        # Calculate heading
        heading = 180 * math.atan2(MAGy, MAGx) / M_PI

        # Only have our heading between 0 and 360
        if heading < 0:
            heading += 360

        ####################################################################
        ###################Tilt compensated heading#########################
        ####################################################################
        # Flip Z for tilt compensation to work.
        MAGz = -MAGz
        # Normalize accelerometer raw values.
        accXnorm = ACCx / math.sqrt(ACCx * ACCx + ACCy * ACCy + ACCz * ACCz)
        accYnorm = ACCy / math.sqrt(ACCx * ACCx + ACCy * ACCy + ACCz * ACCz)

        # Calculate pitch and roll
        pitch = math.asin(accXnorm)
        roll = -math.asin(accYnorm / math.cos(pitch))

        # Calculate the new tilt compensated values
        # X compensation
        magXcomp = MAGx * math.cos(pitch) + MAGz * math.sin(pitch)

        # Y compensation
        magYcomp = MAGx * math.sin(roll) * math.sin(pitch) + MAGy * math.cos(roll) - MAGz * math.sin(roll) * math.cos(pitch)

        # Calculate tilt compensated heading
        tiltCompensatedHeading = 180 * math.atan2(magYcomp, magXcomp) / M_PI

        if tiltCompensatedHeading < 0:
            tiltCompensatedHeading += 360

        ##################### END Tilt Compensation ########################
        ##################### Pressure Reading       ########################
        temperature,pressure,altitude = bmp388.get_temperature_and_pressure_and_altitude()
        ##################### END Pressure Reading   ########################
        
        data = [round(kalmanX, 1),
                round(kalmanY, 1),
                round(((ACCGx * 0.244) / 1000), 1),
                round(((ACCGy * 0.244) / 1000), 1),
                round(((ACCGz * 0.244) / 1000), 1),
                round(((pressure/100)/101325), 1),
                round((temperature/100), 1),
                round((altitude/100), 1),
                round((heading), 1),
                round(elasped_time, 1),
                round(brainACC['x'], 1),
                round(brainACC['y'], 1),
                round(brainACC['z'], 1)]
        data_writer.writerow(data)
        data_out = (','.join(map(str, data)) + '\n').encode()
        print(data)
        if(radio is not None):
            radio.write(data_out)
        time.sleep(0.05)
        end_time = time.time()
        elasped_time += end_time - start_time
        # slow program down a bit, makes the output more readable
        
