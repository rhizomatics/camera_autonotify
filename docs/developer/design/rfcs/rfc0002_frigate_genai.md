# RFC 0002 - Frigate GenAI Notifications

## Design

Add, by discovery or manual add entry, if Frigate is configured to send GenAI summaries over `frigate/tracked_object_update` mqtt topic.

Use this as an extra source of notifications, with consistent handling of images and URLs as the existing Frigate integration. The example automation below comes from existing live Home Assistant install.

Break out the risk based conditions in example automation into a common prioritization that works for any notification source. Use the supernotify priority settings, and allow rules to be added based on plain strings or regular expressions. The rule can also silence the notification instead of de-prioritizing, or select one or more Supernotify scenarios.

The MQTT topic prefix can be customizes, since Frigate allows this to be overridden.

## Documentation

This should have its own docs page, with suggested prompt prefix and rules.

## Example Prompt

This prefix comes form a live Frigate installation, and is followed by a detailed description of the property, cameras and occupants.

```jinja2
Analyze the {label} in these images from the {camera} security
camera. Begin the summary with the risk level in upper case, one of NO
RISK, LOW RISK, MEDIUM RISK, HIGH RISK or CRITICAL RISK. The summary will
be read out on an Alexa device so keep it short. Focus on the actions,
behavior, and potential intent of the {label}, rather than just describing
its appearance.
```

## Example Automation

```yaml
alias: Frigate GenAI Alerts
description: ''
triggers:
  - trigger: mqtt
    topic: frigate/tracked_object_update
    value_template: '{{ value_json.type }}'
    payload: description
conditions:
  - condition: template
    value_template: >-
      {{trigger.payload_json is defined and not
      trigger.payload_json.description.startswith('LOW') and not
      trigger.payload_json.description.startswith('NO RISK') and not
      trigger.payload_json.description.startswith('UNCLEAR') and not
      trigger.payload_json.description.startswith('UNKNOWN') and not
      trigger.payload_json.description.startswith('UNCERTAIN')}}
actions:
  - action: supernotify.notify
    metadata: {}
    data:
      message: >-
        {% set description = trigger.payload_json.description %} {{ description
        | regex_replace('^(\w+)\s+RISK\s+','',ignorecase=True) | lower}}
      title: Update on activity at {{trigger.payload_json.camera}}
      priority: >-
        {% set regex = "(\w+)\s+RISK\s+.*" %} {% set description =
        trigger.payload_json.description %} {% if description is
        match(regex,ignorecase=True) %} {{ description |
        regex_findall_index(regex,ignorecase=True) | lower}} {% else %} medium
        {% endif %}
      media:
        snapshot_url: http://10.111.10.111:8123/api/frigate/notifications/{{trigger.payload_json.id}}/thumbnail.jpg
        camera_entity_id: camera.{{trigger.payload_json.camera}}
mode: single
```