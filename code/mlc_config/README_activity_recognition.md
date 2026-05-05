## 1 - Introduction

The activity recognition algorithm described in this example is intended for smartphone applications since all the data logs collected for this purpose have been acquired with a smartphone carried in the user's pocket.
The activities recognized in this example are: Stationary, Walking, Jogging, Biking and Driving.
A limited subset of data logs for this example is available [here](./datalogs/).

For information on how to integrate this algorithm in the target platform, please follow the instructions available in the README file of the [application_examples]( https://github.com/STMicroelectronics/STMems_Machine_Learning_Core/tree/master/application_examples ) folder.

For information on how to create similar algorithms, please follow the instructions provided in the [configuration_examples]( https://github.com/STMicroelectronics/STMems_Machine_Learning_Core/tree/master/configuration_examples ) folder.


## 2 - Sensor configuration and orientation

The accelerometer is configured with ±4 *g* full scale and 26 Hz output data rate.

Any sensor orientation is allowed for this algorithm.


## 3 - Machine Learning Core configuration

Four features have been used (mean, variance, peak-to-peak, zero-crossing), and two different filters have been applied to the accelerometer input data.
The MLC runs at 26 Hz, computing features on windows of 75 samples (corresponding to almost 3 seconds).
One decision tree with around 120 nodes has been configured to detect the different classes.
A meta-classifier has not been used.

- MLC0_SRC (70h) register values
  - 0 = Stationary
  - 1 = Walking
  - 4 = Jogging
  - 8 = Biking
  - 12 = Driving


## 4 - Interrupts

The configuration generates an interrupt (pulsed and active high) on the INT1 pin every time the register MLC0_SRC (70h) is updated with a new value. The duration of the interrupt pulse is 38.5 ms in this configuration.

------

**More information: [http://www.st.com](http://st.com/MEMS)**

**Copyright © 2022 STMicroelectronics**

## File hashes (SHA-256)

These hashes document the exact versions of the files committed to
the repo. To verify integrity:

\`\`\`bash
sha256sum lsm6dsox_activity_recognition_for_mobile.h \\
          lsm6dsox_activity_recognition_for_mobile.ucf \\
          mlc_activity.h \\
          st_h_to_ours.py
\`\`\`

Expected:

\`\`\`
c3422398af233bc1ba1b46637f566d2c2c61285f787de2e29db2ba8d968d48f9  lsm6dsox_activity_recognition_for_mobile.h
12dd20d40a419f17f3bcf18314e3fb6d3f0fc335b4a7532fa7d2c39fa08600a1  lsm6dsox_activity_recognition_for_mobile.ucf
52cf9a51229b81e3e8e17a30e309d84c3e1ec36f1ba5144ef9db94db632e82bc  mlc_activity.h
9f6c704231e8c443494989449f2e173125496cc2fddba0c74a70621102a031b6  st_h_to_ours.py
\`\`\`

The .h and .ucf hashes correspond to the upstream STMicroelectronics
publication available from MEMS Studio (Activity Recognition for
Mobile reference config).
