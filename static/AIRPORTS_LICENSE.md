# Airport data attribution

`airports.csv` in this directory is a filtered derivative of the
[OpenFlights Airport Database](https://openflights.org/data.php)
(`data/airports.dat`, fetched 2026-08-27 from
https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat),
which is itself sourced primarily from [OurAirports](https://ourairports.com/).

That data is licensed under the **Open Database License (ODbL) v1.0**:
https://raw.githubusercontent.com/jpatokal/openflights/master/data/LICENSE
(mirror: https://opendatacommons.org/licenses/odbl/1-0/).

## What was done to it

The original file has 14 columns for ~7,700 airports/airfields worldwide. This
project only needs IATA → country/timezone resolution for commercial flights,
so `airports.csv` keeps only rows with a valid 3-letter IATA code (6,072 of
them) and only the `iata`, `name`, `country`, `tz` (IANA timezone) columns.
This is a Derivative Database under ODbL §1.0/§4.4, and is distributed here
under the same license as required by §4.4(a)(i).

## Notice (ODbL §4.2/§4.3)

Contains information from the OpenFlights Airport Database
(https://openflights.org/data.php), which is made available under the Open
Database License (ODbL): https://opendatacommons.org/licenses/odbl/1-0/.
