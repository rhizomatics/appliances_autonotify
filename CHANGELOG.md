# 0.3.1
- *Notify progress* switch in the settings of each appliance, above the sections and off by default, to be sent a notification every 10% of the cycle. The Live Activity is silently updated either way
# 0.3.0
- Simpler install: one screen with a switch for automatic discovery, on by default, which sets up every appliance found now and later with no settings to fill in
- *Automatic discovery* is listed on the integration's page with the appliances, where the switch can be changed
- With automatic discovery off, a discovered appliance is added with a single confirmation
- A power monitored appliance is added with one form, from *Add service*
- Settings are in three closed sections: start message, end message and notification targets
- Titles and messages are shown as they'll be sent, "Dishwasher started", with no `{name}` template
- Without Supernotify, targets are optional, defaulting to every phone with the Home Assistant app
# 0.2.2
- Progress bar updated as soon after creation as possible, when the appliance first reports it
