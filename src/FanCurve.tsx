import {
  ButtonItem,
  ConfirmModal,
  Field,
  PanelSection,
  PanelSectionRow,
  SliderField,
} from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { t } from "./i18n";
import { FanState, State } from "./types";

const MIN_CURVE = [44, 48, 55, 60, 71, 79, 87, 87, 100, 100];
const TEMPERATURES = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100];

const setFanCurve = callable<
  [points: number[] | null, enforce_min: boolean],
  State
>("set_fan_curve");

function startPoints(fan: FanState): number[] {
  const enforce = fan.enforce_min ?? true;
  const min = fan.min && fan.min.length === 10 ? fan.min : MIN_CURVE;
  const points = fan.points;
  if (fan.active && points && points.length === 10) return [...points];
  if (enforce) return [...min];
  // No minimums and no active custom curve: 0 except the 90 °C / 100 °C guard.
  return [0, 0, 0, 0, 0, 0, 0, 0, 100, 100];
}

function minFor(fan: FanState, index: number, enforce: boolean): number {
  if (!enforce) return index >= 8 ? 100 : 0;
  if (fan.min && fan.min.length === 10) return fan.min[index];
  return MIN_CURVE[index];
}

export function FanCurveSection(props: { fan: FanState; onState: (s: State) => void }) {
  const { fan, onState } = props;
  const enforce = fan.enforce_min ?? true;
  const [points, setPoints] = useState<number[]>(startPoints(fan));
  const [confirmDisable, setConfirmDisable] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    setPoints(startPoints(fan));
  }, [fan.active, fan.enforce_min, fan.points?.join(","), fan.min?.join(",")]);

  if (!fan.available) {
    return (
      <PanelSection title={t("fanCurve")}>
        <PanelSectionRow>{t("notAvailable")}</PanelSectionRow>
      </PanelSection>
    );
  }

  const push = async (next: number[], enforceNext: boolean = enforce) => {
    setPoints(next);
    const st = await setFanCurve(next, enforceNext);
    onState(st);
    setPoints(startPoints(st.fan_curve));
  };

  const change = (i: number, value: number) => {
    const next = [...points];
    if (enforce) {
      next[i] = Math.max(minFor(fan, i, true), value);
      // Same rule as the backend: the safe curve never goes down with temp.
      for (let j = i + 1; j < next.length; j++) {
        next[j] = Math.max(next[j], next[j - 1]);
      }
    } else {
      next[i] = Math.max(0, Math.min(100, value));
      // The 90 °C and 100 °C guard is never editable, even without minimums.
      next[8] = 100;
      next[9] = 100;
    }
    setPoints(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => push(next), 450);
  };

  const reset = async () => {
    const st = await setFanCurve(null, true);
    onState(st);
    setPoints(startPoints(st.fan_curve));
  };

  return (
    <PanelSection title={t("fanCurve")}>
      <PanelSectionRow>
        <Field label={t("fanState")} bottomSeparator="none">
          {fan.active
            ? enforce
              ? t("fanCustom")
              : t("fanCustomUnsafe")
            : t("fanFactory")}
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label={enforce ? t("fanCurveDesc") : t("fanUnsafeDesc")} bottomSeparator="none" />
      </PanelSectionRow>
      {points.map((value, i) => (
        <PanelSectionRow key={i}>
          <SliderField
            label={`${fan.temperatures?.[i] ?? TEMPERATURES[i]} °C`}
            value={value}
            min={minFor(fan, i, enforce)}
            max={100}
            step={1}
            showValue
            onChange={(v) => change(i, v)}
          />
        </PanelSectionRow>
      ))}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => push([...MIN_CURVE], true)}>
          {t("fanMinCurve")}
        </ButtonItem>
      </PanelSectionRow>
      {enforce ? (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => setConfirmDisable(true)}>
            {t("fanDisableMin")}
          </ButtonItem>
        </PanelSectionRow>
      ) : (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => push([...MIN_CURVE], true)}>
            {t("fanEnableMin")}
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={reset}>
          {t("fanRestore")}
        </ButtonItem>
      </PanelSectionRow>
      {confirmDisable && (
        <ConfirmModal
          strTitle={t("fanDisableMin")}
          strDescription={t("fanDisableConfirm")}
          strOKButtonText={t("fanDisableOk")}
          strCancelButtonText={t("cancel")}
          bDestructiveWarning
          onOK={() => {
            setConfirmDisable(false);
            push(points, false);
          }}
          onCancel={() => setConfirmDisable(false)}
        />
      )}
    </PanelSection>
  );
}
