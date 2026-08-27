"""The pipeline version, in a module with no heavy imports.

`PIPELINE_VERSION` is recorded on every analysis run and used to key stored
artifacts, so the API needs the string constantly. Importing it from
`pipeline` would drag in OpenCV and MediaPipe — roughly 250 MB of resident
memory in a process that never decodes a frame.
"""

PIPELINE_VERSION = "2.0.0"
