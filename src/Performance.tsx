import { ButtonItem, DropdownItem, Field, PanelSection, PanelSectionRow, SliderField, ToggleField } from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { t } from "./i18n";
import { PerfCfg, PerfState, State } from "./types";

const setPerf = callable<
  [boost: boolean | null, epp: string | null, gpu_max: number | null, tdp: number | null],
  State
>("set_perf");

// Measured on a Legion Go S (Z2 Go) with tools/eff_bench.py — see README.
// Z2 Go, 15 W limit: boost off halves package power at 25 % CPU load (15.4 → 7.7 W,
// 70 → 50 °C) keeping 74 % of the throughput; at full load it costs ~3 %.
// EPP "power" and GPU caps were measured to be *less* or not more efficient.
export const SAVER: Omit<PerfCfg, "tdp"> = { boost: false, epp: "balance_power", gpu_max: null };
const RESET: PerfCfg = { boost: null, epp: null, gpu_max: null, tdp: null };

const EPP_LABEL: Record<string, () => string> = {
  performance: () => t("eppPerformance"),
  balance_performance: () => t("eppBalancePerf"),
  balance_power: () => t("eppBalancePower"),
  power: () => t("eppPower"),
};

export function PerformanceSection(props: {
  perf: PerfState;
  cfg: PerfCfg;
  onState: (s: State) => void;
}) {
  const { perf, onState } = props;
  const [cfg, setCfg] = useState<PerfCfg>(props.cfg);
  const [gpuMhz, setGpuMhz] = useState<number>(props.cfg.gpu_max ?? 1000);
  const [tdpW, setTdpW] = useState<number>(props.cfg.tdp ?? props.perf.tdp ?? 15);
  const timer = useRef<number | undefined>(undefined);
  const tdpTimer = useRef<number | undefined>(undefined);
  useEffect(() => setCfg(props.cfg), [JSON.stringify(props.cfg)]);
  useEffect(() => {
    if (props.cfg.tdp != null) setTdpW(props.cfg.tdp);
    else if (props.perf.tdp != null) setTdpW(props.perf.tdp);
  }, [props.cfg.tdp, props.perf.tdp]);

  if (!perf.available) {
    return (
      <PanelSection title={t("performance")}>
        <PanelSectionRow>{t("notAvailable")}</PanelSectionRow>
      </PanelSection>
    );
  }

  const push = async (next: PerfCfg) => {
    setCfg(next);
    onState(await setPerf(next.boost, next.epp, next.gpu_max, next.tdp));
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
          onChange={(on) =>
            push(
              on
                ? { ...cfg, boost: SAVER.boost, epp: SAVER.epp, gpu_max: SAVER.gpu_max }
                : { ...cfg, boost: null, epp: null, gpu_max: null },
            )
          }
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
      {perf.tdp_available ? (
        <>
          <PanelSectionRow>
            <ToggleField
              label={t("tdpControl")}
              description={t("tdpDesc")}
              checked={cfg.tdp != null}
              onChange={(on) => push({ ...cfg, tdp: on ? tdpW : null })}
            />
          </PanelSectionRow>
          {cfg.tdp != null && (
            <PanelSectionRow>
              <SliderField
                label={t("tdpWatts")}
                value={tdpW}
                min={perf.tdp_range[0] ?? 5}
                max={perf.tdp_range[1] ?? 40}
                step={1}
                showValue
                onChange={(v) => {
                  setTdpW(v);
                  window.clearTimeout(tdpTimer.current);
                  tdpTimer.current = window.setTimeout(() => push({ ...cfg, tdp: v }), 350);
                }}
              />
            </PanelSectionRow>
          )}
        </>
      ) : (
        <PanelSectionRow>
          <Field label={t("tdp")} bottomSeparator="none">
            {t("notAvailable")}
          </Field>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => push(RESET)}>
          {t("perfReset")}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
