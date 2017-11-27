# PickleHome

## Overview

PickleHome runs on a [Intel NUC](https://www.intel.com/content/www/us/en/products/boards-kits/nuc.html) living in my media cabinet, running [Ubuntu Server](https://www.ubuntu.com/server). Services are managed by [Docker](https://docker.com/) and [docker-compose](https://docs.docker.com/compose/) (ie the heart of this repo is its `docker-compose.yml`).

[Home Assistant](https://home-assistant.io) is the (other) heart. [picklehome-homeassistant-config](https://github.com/technicalpickles/picklehome-homeassistant-config) contains all the configuration for it (less [secrets](https://home-assistant.io/docs/configuration/secrets/)). The services are either in support of Home Assistant configuration, or provide Home Assistant integration to other platforms.


## Aspirations

These are some ideas I try to keep in mind while designing and automating. I just don't always succeed at doing so :joy:

- Build for convenience, comfort, and security of the entire household, not just myself
- Design for voice control as the primary interface, with any visual interactions being secondary or backup
- Try to keep Home Assistant as the central hub and source of truth
- Backup everything
- Prefer devices with local control to cloud control
- Prefer devices that have open APIs
- Prefer APIs over HTTP or MQTT, and in their absence, build wrappers that expose it that way

## Hardware Components

- Amazon Echo and Echo Dot
- [Hue](http://www2.meethue.com/en-us)
- [Sonos](http://sonos.com/)
- [Vera](http://getvera.com/)
- [Schlage Connect Touch](https://www.schlage.com/en/home/keyless-deadbolt-locks/connect.html)
- [Ecobee 3](https://www.ecobee.com/)
- [Broadlink RM Pro](http://www.ibroadlink.com/rm/)
- [Nest Cam](https://store.nest.com/product/camera/)
- [Etekcity outlets](https://www.amazon.com/Etekcity-Wireless-Electrical-Household-Appliances/dp/B00DQELHBS/ref=sr_1_3?ie=UTF8&qid=1510796065&sr=8-3&keywords=etekcity)

## Documentation

Check out the [wiki](https://github.com/technicalpickles/picklehome/wiki).

## Testing

`script/test` runs yamlint on the YAML files for prettiness, and uses `docker-compose config` to validate the config.

## Development & Deployment

Run `screen` on the NUC and do stuff with `docker-compose` :sweat_smile:
