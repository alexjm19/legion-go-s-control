export type Rgb = [number, number, number];

export interface PerfCfg {
  boost: boolean | null;
  epp: string | null;
  gpu_max: number | null;
  tdp: number | null;
}

export interface PerfState {
  available: boolean;
  boost: boolean | null;
  epp: string | null;
  epps: string[];
  gpu_level: string | null;
  gpu_max: number | null;
  gpu_range: [number | null, number | null];
  tdp: number | null;
  tdp_range: [number | null, number | null];
  tdp_available: boolean;
  tdp_profile: string | null;
  watts: number | null;
  temp: number | null;
}

export interface FanState {
  available: boolean;
  active?: boolean;
  points?: number[];
  temperatures?: number[];
  min?: number[];
  max?: number;
  enforce_min?: boolean;
}

export interface LedCfg {
  enabled: boolean;
  effect: string;
  color: Rgb;
  brightness: number;
  speed: number;
}

export interface PowerLedState {
  available: boolean;
  on: boolean | null;
  backend?: string | null;
}

export interface State {
  settings: {
    charge_mode: string | null;
    server_mode: boolean;
    power_led?: boolean | null;
    touchpad?: { sensitivity?: number } | null;
    perf?: PerfCfg;
  };
  battery: {
    available: boolean;
    mode?: string;
    modes?: string[];
    capacity?: number;
    status?: string;
    power_w?: number | null;
    ac?: boolean | null;
  };
  led: { available: boolean; effects?: string[] } & Partial<LedCfg>;
  power_led: PowerLedState;
  fan_curve: FanState;
  touchpad: {
    available: boolean;
    enabled?: boolean;
    mode?: string;
    modes?: string[];
    bridge?: boolean;
  };
  server: { sleep_blocked: boolean };
  services: {
    available: boolean;
    items: { unit: string; label: string; active: string; frozen: boolean }[];
    game_running: boolean;
    pause_in_game: boolean;
  };
  perf: PerfState;
}
