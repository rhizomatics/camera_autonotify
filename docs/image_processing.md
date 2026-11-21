# Image Processing

Home Assistant's [Image Processing](https://www.home-assistant.io/integrations/image_processing/) integrations, such as [OpenALPR Cloud](https://www.home-assistant.io/integrations/openalpr_cloud/) for number plates, or a face recognition integration, each give an entity that finds plates or faces in a camera's image. They're set up in Home Assistant's YAML, under `image_processing:`.

Each is a source of notifications of its own: the entity scans its own camera, as Home Assistant has it set up to, and each plate or face it finds is notified, by the events of Home Assistant's own interface:

- **Plates**, by the `image_processing.found_plate` event an ANPR/ALPR entity fires, are classified, looked up and counted as any plate is: see [Vehicles](./vehicles.md)
- **Faces**, by the `image_processing.detect_face` event a face recognition entity fires, named or not

An entity is found and set up by itself, as Frigate's cameras are, by its device class, `alpr` or `face`. Each has its own settings: the *Camera* whose image is shown in each notification, which Home Assistant doesn't say of the entity itself, the *Minimum confidence*, a *Quiet period* before the same plate or face is notified again, and the priority of a face, a plate's being by the vehicle rules.

To have a Frigate camera, or any other, scanned too, set up the entity with that camera as its `source`, and its `scan_interval` for how often, each scan being a call to the entity, which may be a paid service.
