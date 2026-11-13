
# Home Assistant Integration

Follow the [policy from HQ on Home Assistant usage](https://github.com/rhizomatics/hq/blob/main/policies/hass-alignment.md).

# Auto Notify vs Supernotify

Logic and config belongs in Auto Notify where its unique to the domain.

This is slightly more nuanced with cameras, since media handling also a core functionality of Supernotify, and will remain so. This includes camera specifics such as PTZ, since a PIR may trigger an automation which wants Supernotify to move and zoom the camera prior to snapping an image.

Any logic that is specific to Frigate, ANPR2MQTT, Unifi Protect etc should not be in Supernotify. Similarly for logic specific to security cameras, such as zones, LPR, face detection etc.

## Pass the Facts On

Auto Notify passes what it knows as facts to Supernotify as `data` on each `supernotify.notify` call, such as the
source, camera, object, recognised names, severity and threat level. Supernotify's scenario conditions can then
match those facts, as `notification_data`, when deciding how a notification is delivered, such as
`notification_data.object == 'bird'`, rather than matching the wording of the message, which changes with phrasing
and with translation.

Supernotify needs no knowledge of what the facts mean, so this keeps domain logic out of it while still letting
delivery depend on the domain.
