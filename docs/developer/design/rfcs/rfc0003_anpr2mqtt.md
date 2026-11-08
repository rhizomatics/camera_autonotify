# RFC 0003 ANPR2MQTT Integration

Add, via manual 'add entry' or auto-discovery, anpr2mqtt entities created by MQTT discovery and notify doing everything the example automation below does.

`anpr2mqtt` has two sources of images - when a camera writes via ftp to a directory, or from a Frigate anpr detection. From either of these it can do additional OCR, and in the UK enrich from DVLA and correct the licence plate.

If the source is Frigate, it should be treated similarly to other Frigate events, such that future versions (or within Supernotify or other components) events can be stitched together either for higher level event recognition or simpler duplicate detection.

### Semantic Levels and Dupe Detection

One concept that some automations have related to dupe detection is semantic levels, e.g. a basic camera event, vs ANPR detection vs ANPR+GenAI or ANPR+DVLA. This is used so that if there are two notifications and the second is semantically richer it still gets thru whereas one at a similar or lower level might be dupe suppressed.

## Example Automation

From a live Home Assistant installation.

```yaml
alias: Driveway ANPR Alert
description: Notify via email, chime, Alexa and mobile push when a vehicle identified
triggers:
  - trigger: state
    entity_id:
      - sensor.anpr_driveway
    attribute: event_time
conditions:
  - condition: not
    conditions:
      - condition: state
        entity_id: sensor.anpr_driveway
        state:
          - unavailable
          - unknown
actions:
  - action: supernotify.notify
    metadata: {}
    data:
      message: >-
        {{ trigger.to_state.attributes.description }} with {{
        trigger.to_state.attributes.plate }} spotted at {{
        trigger.to_state.attributes.camera }} camera{% if
        trigger.to_state.attributes.vehicle_direction is defined %}, moving {{
        trigger.to_state.attributes.vehicle_direction }}{% endif %}

        {% if trigger.to_state.attributes.history.previous_sightings == 0 %} Not
        previously sighted  {% else %}  with {{
        trigger.to_state.attributes.history.previous_sightings }} previous
        sightings. {% endif %} {% if
        trigger.to_state.attributes.history.last_seen is defined and
        trigger.to_state.attributes.history.last_seen is not none %} last seen
        on {{ trigger.to_state.attributes.history.last_seen[:10] }} at {{
        trigger.to_state.attributes.history.last_seen[11:16] }}   {% endif %}

        {% if 'reg_info' in trigger.to_state.attributes and
        trigger.to_state.attributes.reg_info is not none %}  DVLA info: {{
        trigger.to_state.attributes.reg_info }}   {% endif %}

        {% if 'hourly_counts' in trigger.to_state.attributes.history and
        trigger.to_state.attributes.history.hourly_counts is not none %}  Visit
        History: {% for time,count in
        trigger.to_state.attributes.history.hourly_counts.items() %}
          {{ time }}{% if int(time) < 12 %}am{% else %}pm{% endif %} : {{ count }} times
        {% endfor %}{% endif %}
      title: >-
        {{ trigger.to_state.attributes.description }} spotted on {{
        trigger.to_state.attributes.camera }} camera
      priority: '{{ trigger.to_state.attributes.priority }}'
      spoken_message: >-
        {{ trigger.to_state.attributes.description }} with {{
        trigger.to_state.attributes.plate }} spotted at {{
        trigger.to_state.attributes.camera }} camera{% if
        trigger.to_state.attributes.vehicle_direction is defined %}, moving {{
        trigger.to_state.attributes.vehicle_direction }}{% endif %}
      apply_scenarios: >-
        {% if trigger.to_state.attributes.known %}known_vehicle{% else
        %}unknown_vehicle{% endif %}
      constrain_scenarios:
        - known_vehicle
        - unknown_vehicle
      media:
        camera_entity_id: image.anpr_{{trigger.to_state.attributes.camera}}
        snapshot_url: >-
          {% if 'event_image_url' in trigger.to_state.attributes %}{{
          trigger.to_state.attributes.event_image_url }}{% endif %}
mode: single

```
