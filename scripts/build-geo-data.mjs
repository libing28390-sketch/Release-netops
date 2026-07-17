import fs from 'node:fs';
import path from 'node:path';
import { Country, State, City } from 'country-state-city';

const root = path.resolve(process.cwd(), 'public', 'data', 'geo');
const citiesRoot = path.join(root, 'cities');
// The CMDB treats Hong Kong, Macau and Taiwan as China regional entries,
// never as separate countries. Keep the source package's ISO data only as
// an input and normalize the catalog at build time.
const CHINA_REGIONS = new Set(['HK', 'MO', 'TW']);
fs.rmSync(root, { recursive: true, force: true });
fs.mkdirSync(citiesRoot, { recursive: true });

const writeJson = (file, value) => {
  fs.writeFileSync(file, `${JSON.stringify(value)}\n`, 'utf8');
};

writeJson(
  path.join(root, 'countries.json'),
  Country.getAllCountries()
    .filter(({ isoCode }) => !CHINA_REGIONS.has(isoCode))
    .map(({ name, isoCode }) => ({ name, isoCode }))
);

writeJson(
  path.join(root, 'states.json'),
  State.getAllStates().map(({ name, isoCode, countryCode }) => ({ name, isoCode, countryCode }))
);

const citiesByCountry = new Map();
for (const city of City.getAllCities()) {
  // The upstream package contains Taiwan as a country. Re-home its city
  // records under China's Taiwan regional code so the UI has one country
  // hierarchy and the city filter still works.
  const countryCode = CHINA_REGIONS.has(city.countryCode) ? 'CN' : city.countryCode;
  const stateCode = CHINA_REGIONS.has(city.countryCode) ? city.countryCode : city.stateCode;
  if (city.countryCode === 'CN' && CHINA_REGIONS.has(city.stateCode)) continue;
  const list = citiesByCountry.get(countryCode) || [];
  list.push({ name: city.name, stateCode, countryCode });
  citiesByCountry.set(countryCode, list);
}

for (const [countryCode, cities] of citiesByCountry) {
  cities.sort((left, right) => left.name.localeCompare(right.name));
  writeJson(path.join(citiesRoot, `${countryCode}.json`), cities);
}

console.log(`Generated ${Country.getAllCountries().length} countries, ${State.getAllStates().length} states and ${City.getAllCities().length} cities under ${root}`);
