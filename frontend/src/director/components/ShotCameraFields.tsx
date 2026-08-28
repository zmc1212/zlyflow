import { Select } from "antd"
import {
  CAMERA_ANGLE_LABELS, CAMERA_LIGHTING_LABELS, CAMERA_MOVEMENT_LABELS, CAMERA_SCALE_LABELS,
  CameraAngle, CameraDirection, CameraLighting, CameraMovement, CameraScale, defaultCameraDirection,
} from "../types"

export default function ShotCameraFields({
  camera,
  onChange,
}: {
  camera?: CameraDirection | null
  onChange: (camera: CameraDirection) => void
}) {
  const value = camera || defaultCameraDirection()
  return (
    <div className="director-camera-fields">
      <label>
        <span>景别</span>
        <Select
          aria-label="景别"
          className="w-full"
          value={value.scale}
          options={Object.entries(CAMERA_SCALE_LABELS).map(([key, item]) => ({ value: key, label: item.label }))}
          onChange={(scale: CameraScale) => onChange({ ...value, scale })}
        />
      </label>
      <label>
        <span>运镜</span>
        <Select
          aria-label="运镜"
          className="w-full"
          value={value.movement}
          options={Object.entries(CAMERA_MOVEMENT_LABELS).map(([key, item]) => ({ value: key, label: item.label }))}
          onChange={(movement: CameraMovement) => onChange({ ...value, movement })}
        />
      </label>
      <label>
        <span>机位</span>
        <Select
          aria-label="机位"
          className="w-full"
          value={value.angle}
          options={Object.entries(CAMERA_ANGLE_LABELS).map(([key, item]) => ({ value: key, label: item.label }))}
          onChange={(angle: CameraAngle) => onChange({ ...value, angle })}
        />
      </label>
      <label>
        <span>布光</span>
        <Select
          aria-label="布光"
          className="w-full"
          value={value.lighting}
          options={Object.entries(CAMERA_LIGHTING_LABELS).map(([key, item]) => ({ value: key, label: item.label }))}
          onChange={(lighting: CameraLighting) => onChange({ ...value, lighting })}
        />
      </label>
    </div>
  )
}
