# RFC0010 - Unifi Protect

[Unifi Protect](https://www.home-assistant.io/integrations/unifiprotect/) is used by 4.5% of Home Assistant installs, which makes it relatively popular.

Auto discover Camera devices and set up a Camera AutoNotify linked device.

## Events

Support the following Home Assistant events:

- Doorbell Ring Event
- Vehicle Detection Event
  - Including integration with existing LPR functionality
- Motion Detection Event
- Smart Detection Event

Use the `confidence` attributes for selected thresholds, linked to priorities or silencing.

Don't double notify if a vehicle triggers 'smart' and 'vehicle' detection events.
