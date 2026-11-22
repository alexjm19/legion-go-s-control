import { ButtonItem, DropdownItem, Field, PanelSection, PanelSectionRow, SliderField, ToggleField } from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { t } from "./i18n";

export interface PerfCfg {
  boost: boolean | null;
  epp: string | null;
  gpu_max: number | null;
}

export interface PerfState {
  available: boolean;
  boost: boolean | null;
  epp: string | null;
  epps: string[];
  gpu_level: string | null;
  gpu_max: number | null;
  gpu_range: [number | null, number | null];
  watts: number | null;
  temp: number | null;
}

const setPerf = callable<[boost: boolean | null, epp: string | null, gpu_max: number | null], any>("set_perf");

// Measured on a Legion Go S (Z2 Go) with tools/eff_bench.py — see README.
// Z2 Go, 15 W limit: boost off halves package power at 25 % CPU load (15.4 → 7.7 W,
// 70 → 50 °C) keeping 74 % of the throughput; at full load it costs ~3 %.
// EPP "power" and GPU caps were measured to be *less* or not more efficient.
export const SAVER: PerfCfg = { boost: false, epp: "balance_power", gpu_max: null };
const UNTOUCHED: PerfCfg = { boost: null, epp: null, gpu_max: null };

const EPP_LABEL: Record<string, () => string> = {
  performance: () => t("eppPerformance"),
  balance_performance: () => t("eppBalancePerf"),
  balance_power: () => t("eppBalancePower"),
  power: () => t("eppPower"),
};

export function PerformanceSection(props: {
  perf: PerfState;
  cfg: PerfCfg;
  onState: (s: any) => void;
}) {
  const { perf, onState } = props;
  const [cfg, setCfg] = useState<PerfCfg>(props.cfg);
  const [gpuMhz, setGpuMhz] = useState<number>(props.cfg.gpu_max ?? 1000);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => setCfg(props.cfg), [JSON.stringify(props.cfg)]);

  if (!perf.available) {
    return (
      <PanelSection title={t("performance")}>
        <PanelSectionRow>{t("notAvailable")}</PanelSectionRow>
      </PanelSection>
    );
  }

  const push = async (next: PerfCfg) => {
    setCfg(next);
    onState(await setPerf(next.boost, next.epp, next.gpu_max));
  };

  const [rmin, rmax] = perf.gpu_range;
  const live =
    (perf.watts != null ? `${perf.watts} W` : "— W") + " · " + (perf.temp != null ? `${perf.temp} °C` : "— °C");
  const isSaver =
    cfg.boost === SAVER.boost && cfg.epp === SAVER.epp && cfg.gpu_max === SAVER.gpu_max;

  return (
    <PanelSection title={t("performance")}>
      <PanelSectionRow>
        <Field label={t("livePower")} bottomSeparator="none">
          {live}
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label={t("saverProfile")}
          description={t("saverDesc")}
          checked={isSaver}
          onChange={(on) => {
                        push(on ? SAVER : UNTOUCHED);
          }}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label={t("cpuBoost")}
          rgOptions={[
            { data: "null", label: t("dontTouch") },
            { data: "on", label: t("on") },
            { data: "off", label: t("off") },
          ]}
          selectedOption={cfg.boost === null ? "null" : cfg.boost ? "on" : "off"}
          onChange={(o) => push({ ...cfg, boost: o.data === "null" ? null : o.data === "on" })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label={t("epp")}
          rgOptions={[{ data: "null", label: t("dontTouch") }].concat(
            perf.epps.map((e) => ({ data: e, label: EPP_LABEL[e]?.() ?? e })),
          )}
          selectedOption={cfg.epp ?? "null"}
          onChange={(o) => push({ ...cfg, epp: o.data === "null" ? null : o.data })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label={t("gpuCap")}
          description={
            cfg.gpu_max ? t("gpuCapOn").replace("{mhz}", String(cfg.gpu_max)) : t("gpuCapOff")
          }
          checked={!!cfg.gpu_max}
          onChange={(on) => push({ ...cfg, gpu_max: on ? gpuMhz : null })}
        />
      </PanelSectionRow>
      {!!cfg.gpu_max && (
        <PanelSectionRow>
          <SliderField
            label={t("gpuMaxMhz")}
            value={gpuMhz}
            min={Math.max(400, rmin ?? 400)}
            max={rmax ?? 2200}
            step={100}
            showValue
            onChange={(v) => {
              setGpuMhz(v);
              window.clearTimeout(timer.current);
              timer.current = window.setTimeout(() => push({ ...cfg, gpu_max: v }), 300);
            }}
          />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => push(UNTOUCHED)}>
          {t("perfReset")}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
