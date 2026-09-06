RackVision Blender build tools

Coordinate contract:
- Metric scene, one Blender unit is one meter.
- X = left/right, Y = front/back, Z = vertical.
- Front faces +Y. Device origin is the chassis center in X, front insertion
  plane in Y, and the bottom of the device in Z.
- 1U = 0.04445 m.

The scripts run inside Blender with bpy. The FastAPI/React runtime does not
depend on Blender. batch_build.py refuses a mass build unless asset keys are
explicitly selected or registry entries opt in with build=true.

