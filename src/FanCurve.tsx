import { ButtonItem, Field, PanelSection, PanelSectionRow, SliderField } from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { t } from "./i18n";
import { FanState, State } from "./types";

const MIN_CURVE = [44, 48, 55, 60, 71, 79, 87, 87, 100, 100];
const TEMPERATURES = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100];

const setFanCurve = callable<[points: number[] | null], State>("set_fan_curve");

function startPoints(fan: FanState): number[] {
  const min = fan.min && fan.min.length === 10 ? fan.min : MIN_CURVE;
  const points = fan.points;
  if (fan.active && points && points.length === 10) return [...points];
  return [...min];
}

export function FanCurveSection(props: { fan: FanState; onState: (s: State) => void }) {
  const { fan, onState } = props;
  const [points, setPoints] = useState<number[]>(startPoints(fan));
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    setPoints(startPoints(fan));
  }, [fan.active, fan.points?.join(","), fan.min?.join(",")]);

  if (!fan.available) {
    return (
      <PanelSection title={t("fanCurve")}>
        <PanelSectionRow>{t("notAvailable")}</PanelSectionRow>
      </PanelSection>
    );
  }

  const push = async (next: number[]) => {
    setPoints(next);
    const st = await setFanCurve(next);
    onState(st);
    setPoints(startPoints(st.fan_curve));
  };

  const change = (i: number, value: number) => {
    const next = [...points];
    next[i] = value;
    // Same rule as the backend: the curve never goes down with temperature.
    for (let j = i + 1; j < next.length; j++) {
      next[j] = Math.max(next[j], next[j - 1]);
    }
    setPoints(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => push(next), 450);
  };

  const reset = async () => {
    const st = await setFanCurve(null);
    onState(st);
    setPoints(startPoints(st.fan_curve));
  };

  return (
    <PanelSection title={t("fanCurve")}>
      <PanelSectionRow>
        <Field label={t("fanState")} bottomSeparator="none">
          {fan.active ? t("fanCustom") : t("fanFactory")}
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label={t("fanCurveDesc")} bottomSeparator="none" />
      </PanelSectionRow>
      {points.map((value, i) => (
        <PanelSectionRow key={i}>
          <SliderField
            label={`${fan.temperatures?.[i] ?? TEMPERATURES[i]} °C`}
            value={value}
            min={fan.min?.[i] ?? MIN_CURVE[i]}
            max={fan.max ?? 100}
            step={1}
            showValue
            onChange={(v) => change(i, v)}
          />
        </PanelSectionRow>
      ))}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => push(startPoints({ ...fan, active: false }))}>
          {t("fanMinCurve")}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={reset}>
          {t("fanRestore")}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
