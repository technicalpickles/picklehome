# Transform a stream of `op item get --format json` objects into the
# PICKLEHOME_LOCATIONS array consumed by climate/locations.py.
#
# Each 1Password item tagged `picklehome-location` contributes one location.
# Custom fields are matched by label: slug, label, latitude, longitude,
# station_macs (comma-separated). latitude/longitude are required; items
# missing either are skipped.
#
# Run over the slurped stream: jq -sc -f scripts/locations-filter.jq
map(
  (reduce (.fields // [])[] as $f ({}; .[$f.label] = $f.value)) as $m
  | select($m.latitude and $m.longitude)
  | {
      slug: ($m.slug // (.title | ascii_downcase | gsub("[^a-z0-9]+"; "-"))),
      label: ($m.label // .title),
      lat: ($m.latitude | tonumber),
      lon: ($m.longitude | tonumber),
      station_macs: (
        ($m.station_macs // "")
        | split(",")
        | map(gsub("^\\s+|\\s+$"; ""))
        | map(select(length > 0))
      )
    }
  # Strip single quotes so the value is safe inside a single-quoted .env line.
  | walk(if type == "string" then gsub("'"; "") else . end)
)
# Home first (the Atlanta default), then alphabetical by slug.
| sort_by(.slug != "home", .slug)
