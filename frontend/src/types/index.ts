export type TriState = "yes" | "no" | "unknown";
export type Species = "dog" | "cat" | "other";
export type Sex = "male" | "female" | "unknown";

export type Animal = {
  id: number;
  stay_id: number | null;
  stay_days?: number | null;
  stay_day_basis?: string | null;
  stay_day_note?: string | null;
  name: string;
  species: Species;
  breed: string | null;
  age_months: number | null;
  sex: Sex;
  health_status: string;
  vaccinated: TriState;
  sterilized: TriState;
  dewormed: TriState;
  intake_date: string;
  intake_at: string;
  photo_url: string | null;
  dataset_scope?: "user" | "historical_demo" | "synthetic_demo";
  external_animal_id?: string | null;
  data_notes?: string[];
};

export type AnimalInput = {
  name: string;
  species: Species;
  breed: string | null;
  age_months: number | null;
  sex: Sex;
  health_status: string;
  vaccinated: TriState;
  sterilized: TriState;
  dewormed: TriState;
  intake_date: string;
  photo_url: string | null;
};

export type ForecastPoint = {
  date: string;
  expected_occupancy: number;
  lower_bound: number;
  upper_bound: number;
};

export type Forecast = {
  mock: boolean;
  mode: "real" | "mock";
  horizon_days: number;
  current_count: number;
  forecast: ForecastPoint[];
  warnings?: string[];
  model_version?: string;
  generated_at?: string;
  interval_method?: string;
  demo?: boolean;
};

export type ModuleResult = {
  mock?: boolean;
  mode?: "real" | "mock" | "rule_based" | "unavailable";
  ml_status?: "unavailable" | "not_trained" | "real";
  warnings?: string[];
  model_version?: string;
  generated_at?: string;
  [key: string]: unknown;
};
