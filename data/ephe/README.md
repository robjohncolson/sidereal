# Swiss Ephemeris files

Place `.se1` files directly in this directory. The binaries are intentionally
ignored by Git; this setup note is retained.

For common modern dates, fetch the official planet and Moon data files:

```bash
curl -fL -o data/ephe/sepl_18.se1 \
  https://raw.githubusercontent.com/aloistr/swisseph/master/ephe/sepl_18.se1
curl -fL -o data/ephe/semo_18.se1 \
  https://raw.githubusercontent.com/aloistr/swisseph/master/ephe/semo_18.se1
```

Use Astrodienst's download guide for other date ranges:
https://www.astro.com/swisseph/swedownload_e.htm

Run charts with `--ephe-path data/ephe --require-swiss-ephemeris` to reject a
silent fallback. Comply with the Swiss Ephemeris license when redistributing
the library or data.
