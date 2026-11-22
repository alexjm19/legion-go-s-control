import {
  ButtonItem,
  DropdownItem,
  Field,
  Focusable,
  PanelSection,
  PanelSectionRow,
  SliderField,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { FaGamepad } from "react-icons/fa";
import { t } from "./i18n";
import { FanCurveSection } from "./FanCurve";
import { PerformanceSection } from "./Performance";
import { LedCfg, Rgb, State } from "./types";

const getState = callable<[], State>("get_state");
const setChargeMode = callable<[mode: string], State>("set_charge_mode");
const setServerMode = callable<[enabled: boolean], State>("set_server_mode");
const setPowerLed = callable<[enabled: boolean], State>("set_power_led");
const setLed = callable<
  [enabled: boolean, effect: string, color: Rgb, brightness: number, speed: number],
  State
>("set_led");
const setTouchpad = callable<
  [enabled: boolean, mode: string, bridge: boolean, sensitivity: number],
  State
>("set_touchpad");

// Presets use the driver's 0-100 per-channel scale.
const PRESETS: { name: string; color: Rgb }[] = [
  { name: "⚪", color: [100, 100, 100] },
  { name: "🔴", color: [100, 0, 0] },
  { name: "🟠", color: [100, 35, 0] },
  { name: "🟡", color: [100, 80, 0] },
  { name: "🟢", color: [0, 100, 0] },
  { name: "🔵", color: [0, 60, 100] },
  { name: "🟣", color: [60, 0, 100] },
  { name: "🩷", color: [100, 10, 60] },
];

const CHARGE_LABEL: Record<string, () => string> = {
  Long_Life: () => t("chargeLongLife"),
  Standard: () => t("chargeStandard"),
  Fast: () => t("chargeFast"),
};

const EFFECT_LABEL: Record<string, () => string> = {
  monocolor: () => t("effectMono"),
  breathe: () => t("effectBreathe"),
  chroma: () => t("effectChroma"),
  rainbow: () => t("effectRainbow"),
};

const CATEGORIES = [
  { id: "energy", label: "categoryEnergy" },
  { id: "cooling", label: "categoryCooling" },
  { id: "lighting", label: "categoryLighting" },
  { id: "input", label: "categoryInput" },
  { id: "system", label: "categorySystem" },
] as const;

type Category = (typeof CATEGORIES)[number]["id"];
const CATEGORY_KEY = "legion-go-s-control-category";

function isCategory(value: string | null): value is Category {
  return value !== null && CATEGORIES.some((c) => c.id === value);
}

function initialCategory(): Category {
  try {
    const stored = window.localStorage.getItem(CATEGORY_KEY);
    return isCategory(stored) ? stored : "energy";
  } catch {
    return "energy";
  }
}

function useDebounced<A extends unknown[]>(fn: (...a: A) => void, ms: number) {
  const timer = useRef<number | undefined>(undefined);
  return (...a: A) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => fn(...a), ms);
  };
}

function Swatch({ color }: { color: Rgb }) {
  const css = `rgb(${color.map((c) => Math.round(c * 2.55)).join(",")})`;
  return (
    <div
      style={{
        width: 22,
        height: 22,
        borderRadius: 11,
        background: css,
        border: "2px solid rgba(255,255,255,0.4)",
      }}
    />
  );
}

function Content() {
  const [s, setS] = useState<State | null>(null);
  const [led, setLedLocal] = useState<LedCfg | null>(null);
  const [category, setCategory] = useState<Category>(initialCategory);

  const selectCategory = (id: string) => {
    if (!isCategory(id)) return;
    setCategory(id);
    try {
      window.localStorage.setItem(CATEGORY_KEY, id);
    } catch {
      // localStorage can be unavailable; the default category still works.
    }
  };

  const refresh = async () => {
    const st = await getState();
    setS(st);
    setSens(st.settings.touchpad?.sensitivity ?? 1);
    if (st.led.available) {
      setLedLocal({
        enabled: !!st.led.enabled,
        effect: st.led.effect ?? "monocolor",
        color: (st.led.color as Rgb) ?? [0, 60, 100],
        brightness: st.led.brightness ?? 80,
        speed: st.led.speed ?? 50,
      });
    }
  };

  useEffect(() => {
    refresh();
    const id = window.setInterval(async () => setS(await getState()), 5000);
    return () => window.clearInterval(id);
  }, []);

  const [sens, setSens] = useState(1);
  const pushSens = useDebounced(async (v: number) => {
    setS(await setTouchpad(true, "relative", true, v));
  }, 300);

  const pushLed = useDebounced(async (cfg: LedCfg) => {
    setS(await setLed(cfg.enabled, cfg.effect, cfg.color, cfg.brightness, cfg.speed));
  }, 250);

  const updateLed = (patch: Partial<LedCfg>) => {
    if (!led) return;
    const next = { ...led, ...patch };
    setLedLocal(next);
    pushLed(next);
  };

  if (!s) {
    return (
      <PanelSection>
        <PanelSectionRow>{t("loading")}</PanelSectionRow>
      </PanelSection>
    );
  }

  const b = s.battery;
  const statusLine = b.available
    ? `${b.capacity}% · ${t("status_" + (b.status ?? "Unknown"))}` +
      (b.power_w != null ? ` · ${b.power_w} W` : "") +
      (b.ac ? ` · ${t("plugged")}` : "")
    : "";

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <Focusable
            flow-children="horizontal"
            style={{ display: "flex", flexWrap: "wrap", gap: 4 }}
          >
            {CATEGORIES.map((c) => (
              <ButtonItem
                key={c.id}
                layout="inline"
                bottomSeparator="none"
                onClick={() => selectCategory(c.id)}
              >
                {category === c.id ? `● ${t(c.label)}` : t(c.label)}
              </ButtonItem>
            ))}
          </Focusable>
        </PanelSectionRow>
      </PanelSection>

      {category === "energy" && (
        <>
          <PanelSection title={t("battery")}>
        {b.available ? (
          <>
            <PanelSectionRow>
              <Field label={statusLine} bottomSeparator="none" />
            </PanelSectionRow>
            <PanelSectionRow>
              <ToggleField
                label={t("chargeLimit")}
                description={t("chargeLimitDesc")}
                checked={b.mode === "Long_Life"}
                onChange={async (on) => setS(await setChargeMode(on ? "Long_Life" : "Standard"))}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <DropdownItem
                label={t("chargeMode")}
                rgOptions={(b.modes ?? []).map((m) => ({
                  data: m,
                  label: CHARGE_LABEL[m]?.() ?? m,
                }))}
                selectedOption={b.mode}
                onChange={async (o) => setS(await setChargeMode(o.data))}
              />
            </PanelSectionRow>
          </>
        ) : (
          <PanelSectionRow>{t("notAvailable")}</PanelSectionRow>
        )}
      </PanelSection>

          <PerformanceSection
            perf={s.perf}
            cfg={s.settings.perf ?? { boost: null, epp: null, gpu_max: null, tdp: null }}
            onState={setS}
          />
        </>
      )}

      {category === "cooling" && <FanCurveSection fan={s.fan_curve} onState={setS} />}

      {category === "lighting" && (
        <>
          <PanelSection title={t("powerLed")}>
        {s.power_led.available ? (
          <PanelSectionRow>
            <ToggleField
              label={t("powerLedOn")}
              description={s.power_led.on ? t("powerLedOnDesc") : t("powerLedOffDesc")}
              checked={!!s.power_led.on}
              onChange={async (on) => setS(await setPowerLed(on))}
            />
          </PanelSectionRow>
        ) : (
          <PanelSectionRow>{t("notAvailable")}</PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title={t("leds")}>
        {s.led.available && led ? (
          <>
            <PanelSectionRow>
              <ToggleField
                label={t("ledsOn")}
                checked={led.enabled}
                onChange={(on) => updateLed({ enabled: on })}
              />
            </PanelSectionRow>
            {led.enabled && (
              <>
                <PanelSectionRow>
                  <DropdownItem
                    label={t("effect")}
                    rgOptions={(s.led.effects ?? []).map((e) => ({
                      data: e,
                      label: EFFECT_LABEL[e]?.() ?? e,
                    }))}
                    selectedOption={led.effect}
                    onChange={(o) => updateLed({ effect: o.data })}
                  />
                </PanelSectionRow>
                <PanelSectionRow>
                  <Field label={t("color")} bottomSeparator="none">
                    <Swatch color={led.color} />
                  </Field>
                </PanelSectionRow>
                <PanelSectionRow>
                  <Focusable
                    flow-children="horizontal"
                    style={{ display: "flex", flexWrap: "wrap", gap: 4 }}
                  >
                    {PRESETS.map((p) => (
                      <ButtonItem
                        key={p.name}
                        layout="inline"
                        bottomSeparator="none"
                        onClick={() => updateLed({ color: p.color })}
                      >
                        {p.name}
                      </ButtonItem>
                    ))}
                  </Focusable>
                </PanelSectionRow>
                {(["red", "green", "blue"] as const).map((ch, i) => (
                  <PanelSectionRow key={ch}>
                    <SliderField
                      label={t(ch)}
                      value={led.color[i]}
                      min={0}
                      max={100}
                      step={1}
                      showValue
                      onChange={(v) => {
                        const c = [...led.color] as Rgb;
                        c[i] = v;
                        updateLed({ color: c });
                      }}
                    />
                  </PanelSectionRow>
                ))}
                <PanelSectionRow>
                  <SliderField
                    label={t("brightness")}
                    value={led.brightness}
                    min={0}
                    max={100}
                    step={5}
                    showValue
                    onChange={(v) => updateLed({ brightness: v })}
                  />
                </PanelSectionRow>
                {led.effect !== "monocolor" && (
                  <PanelSectionRow>
                    <SliderField
                      label={t("speed")}
                      value={led.speed}
                      min={0}
                      max={100}
                      step={5}
                      showValue
                      onChange={(v) => updateLed({ speed: v })}
                    />
                  </PanelSectionRow>
                )}
              </>
            )}
          </>
        ) : (
          <PanelSectionRow>{t("notAvailable")}</PanelSectionRow>
        )}
          </PanelSection>
        </>
      )}

      {category === "input" && (
        <PanelSection title={t("touchpad")}>
        {s.touchpad.available ? (
          <>
            <PanelSectionRow>
              <ToggleField
                label={t("touchpadOn")}
                checked={!!s.touchpad.enabled}
                onChange={async (on) =>
                  setS(await setTouchpad(on, s.touchpad.mode ?? "relative", true, sens))
                }
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <DropdownItem
                label={t("touchpadMode")}
                description={t("touchpadModeDesc")}
                rgOptions={(s.touchpad.modes ?? []).map((m) => ({
                  data: m,
                  label: m === "relative" ? t("tpRelative") : t("tpAbsolute"),
                }))}
                selectedOption={s.touchpad.mode}
                onChange={async (o) =>
                  setS(await setTouchpad(!!s.touchpad.enabled, o.data, true, sens))
                }
              />
            </PanelSectionRow>
            {s.touchpad.mode === "relative" && (
              <PanelSectionRow>
                <SliderField
                  label={t("sensitivity")}
                  description={s.touchpad.bridge ? t("bridgeOn") : t("bridgeOff")}
                  value={sens}
                  min={0.2}
                  max={4}
                  step={0.1}
                  showValue
                  onChange={(v) => {
                    setSens(v);
                    pushSens(v);
                  }}
                />
              </PanelSectionRow>
            )}
          </>
        ) : (
          <PanelSectionRow>{t("notAvailable")}</PanelSectionRow>
        )}
        </PanelSection>
      )}

      {category === "system" && (
        <PanelSection title={t("server")}>
          <PanelSectionRow>
            <ToggleField
              label={t("serverMode")}
              description={s.server.sleep_blocked ? t("serverOnDesc") : t("serverOffDesc")}
              checked={s.settings.server_mode}
              onChange={async (on) => setS(await setServerMode(on))}
            />
          </PanelSectionRow>
        </PanelSection>
      )}
    </>
  );
}

export default definePlugin(() => ({
  name: "Legion Go S Control",
  titleView: <div className={staticClasses.Title}>Legion Go S Control</div>,
  content: <Content />,
  icon: <FaGamepad />,
}));
