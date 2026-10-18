import React from "react";
import {
  AbsoluteFill,
  Sequence,
  Img,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Easing,
} from "remotion";

export type SpotlightRect = {
  x: number; // percentage 0-100
  y: number; // percentage 0-100
  w: number; // percentage 0-100
  h: number; // percentage 0-100
  label?: string;
  color?: string;
};

export type TableData = {
  headers: string[];
  rows: string[][];
  highlightCol?: number;
};

export type ChatStep = {
  stepLabel: string;
  title: string;
  prompt: string;
  note?: string;
};

export type Lesson01Scene = {
  id: string;
  sectionId?: string;
  sectionLabel?: string;
  kind:
    | "title"
    | "full-image"
    | "split-image"
    | "dual-image"
    | "table"
    | "chat-sim"
    | "promises"
    | "worksheet"
    | "dot-flow";
  badge?: string;
  badgeColor?: "blue" | "green" | "amber" | "red" | "purple";
  heading: string;
  sub?: string;
  bullets?: string[];
  steps?: { num: string; title: string; desc: string }[];
  quote?: string;
  tip?: string;
  warning?: string;
  image?: string;
  imageAlt?: string;
  imageCaption?: string;
  secondImage?: string;
  secondImageCaption?: string;
  spotlights?: SpotlightRect[];
  table?: TableData;
  chatSteps?: ChatStep[];
  worksheetItems?: string[];
  checklist?: string[];
  narration: string;
  frames: number;
  startFrame: number;
};

export type Lesson01Build = {
  id: string;
  courseId: string;
  lessonId: string;
  videoType: string;
  lessonTitle: string;
  fps: number;
  width: number;
  height: number;
  totalFrames: number;
  scenes: Lesson01Scene[];
};

export type Lesson01Props = {
  id?: string;
  build?: Lesson01Build;
};

const THEME = {
  bgStart: "#F4F8FD",
  bgEnd: "#FFFFFF",
  cardBg: "#FFFFFF",
  cardBorder: "#E2E8F0",
  navy: "#0F172A",
  slate: "#334155",
  muted: "#64748B",
  blue: "#2563EB",
  blueLight: "#EFF6FF",
  blueBorder: "#BFDBFE",
  green: "#059669",
  greenLight: "#ECFDF5",
  greenBorder: "#A7F3D0",
  amber: "#D97706",
  amberLight: "#FFFBEB",
  amberBorder: "#FDE68A",
  red: "#DC2626",
  redLight: "#FEF2F2",
  redBorder: "#FECACA",
  purple: "#7C3AED",
  purpleLight: "#F5F3FF",
  purpleBorder: "#DDD6FE",
};

const FONT_SANS =
  "'Hiragino Kaku Gothic ProN', 'Hiragino Sans', 'Noto Sans JP', sans-serif";
const FONT_ROUND =
  "'Hiragino Maru Gothic ProN', 'Hiragino Sans', 'Noto Sans JP', sans-serif";
const FONT_MONO = "'SF Mono', 'Menlo', 'Hiragino Sans', monospace";

const BADGE_PALETTE = {
  blue: { bg: "#2563EB", fg: "#FFFFFF", soft: "#DBEAFE" },
  green: { bg: "#059669", fg: "#FFFFFF", soft: "#D1FAE5" },
  amber: { bg: "#D97706", fg: "#FFFFFF", soft: "#FEF3C7" },
  red: { bg: "#DC2626", fg: "#FFFFFF", soft: "#FEE2E2" },
  purple: { bg: "#7C3AED", fg: "#FFFFFF", soft: "#EDE9FE" },
};

const resolveAssetPath = (relPath?: string): string => {
  if (!relPath) return "";
  const clean = relPath.replace(/^\.\.\//, "").replace(/^\.\//, "");
  if (/^[A-Za-z0-9_-]+\/images\//.test(clean)) {
    return clean;
  }
  return `lesson01/${clean}`;
};

// TotonouMovie-inspired animated marker underline
const HighlightMarker: React.FC<{
  children: React.ReactNode;
  color?: string;
  delay?: number;
}> = ({ children, color = "rgba(251, 191, 36, 0.45)", delay = 8 }) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [delay, delay + 18], [0, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      <span
        style={{
          position: "absolute",
          left: 0,
          bottom: 4,
          height: "36%",
          width: `${progress}%`,
          backgroundColor: color,
          borderRadius: 6,
          zIndex: 0,
        }}
      />
      <span style={{ position: "relative", zIndex: 1 }}>{children}</span>
    </span>
  );
};

// TotonouMovie-inspired spring badge
const AnimatedBadge: React.FC<{
  text: string;
  color?: keyof typeof BADGE_PALETTE;
}> = ({ text, color = "blue" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const scale = spring({
    frame,
    fps,
    config: { damping: 12, stiffness: 160, mass: 0.6 },
  });
  const c = BADGE_PALETTE[color] ?? BADGE_PALETTE.blue;
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        backgroundColor: c.bg,
        color: c.fg,
        fontFamily: FONT_ROUND,
        fontWeight: 800,
        fontSize: 23,
        padding: "8px 22px",
        borderRadius: 999,
        letterSpacing: "0.05em",
        transform: `scale(${scale})`,
        boxShadow: "0 6px 16px rgba(37, 99, 235, 0.22)",
        marginBottom: 14,
      }}
    >
      {text}
    </div>
  );
};

const SectionHeading: React.FC<{
  badge?: string;
  badgeColor?: keyof typeof BADGE_PALETTE;
  heading: string;
  sub?: string;
}> = ({ badge, badgeColor = "blue", heading, sub }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const slide = spring({
    frame,
    fps,
    config: { damping: 200 },
    durationInFrames: 20,
  });
  const subOpacity = interpolate(frame, [8, 22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div style={{ marginBottom: 24 }}>
      {badge && <AnimatedBadge text={badge} color={badgeColor} />}
      <div
        style={{
          fontFamily: FONT_ROUND,
          fontWeight: 800,
          fontSize: 48,
          color: THEME.navy,
          lineHeight: 1.25,
          opacity: slide,
          transform: `translateY(${interpolate(slide, [0, 1], [16, 0])}px)`,
        }}
      >
        <HighlightMarker>{heading}</HighlightMarker>
      </div>
      {sub && (
        <div
          style={{
            fontFamily: FONT_SANS,
            fontSize: 25,
            fontWeight: 500,
            color: THEME.slate,
            marginTop: 10,
            opacity: subOpacity,
            lineHeight: 1.45,
          }}
        >
          {sub}
        </div>
      )}
    </div>
  );
};

const CalloutBox: React.FC<{
  type: "tip" | "warning" | "quote";
  text: string;
  delay?: number;
}> = ({ type, text, delay = 22 }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [delay, delay + 14], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const translateY = interpolate(frame, [delay, delay + 14], [14, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

  const config =
    type === "warning"
      ? {
          bg: THEME.redLight,
          border: THEME.redBorder,
          accent: THEME.red,
          label: "注意点",
          icon: "⚠️",
        }
      : type === "quote"
        ? {
            bg: THEME.blueLight,
            border: THEME.blueBorder,
            accent: THEME.blue,
            label: "ポイント",
            icon: "💡",
          }
        : {
            bg: THEME.greenLight,
            border: THEME.greenBorder,
            accent: THEME.green,
            label: "ヒント",
            icon: "✨",
          };

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${translateY}px)`,
        backgroundColor: config.bg,
        border: `2px solid ${config.border}`,
        borderLeft: `8px solid ${config.accent}`,
        borderRadius: 16,
        padding: "16px 22px",
        marginTop: 16,
        display: "flex",
        alignItems: "flex-start",
        gap: 14,
      }}
    >
      <div style={{ fontSize: 28, lineHeight: 1.2 }}>{config.icon}</div>
      <div style={{ flex: 1 }}>
        <div
          style={{
            fontFamily: FONT_ROUND,
            fontWeight: 800,
            fontSize: 20,
            color: config.accent,
            marginBottom: 4,
          }}
        >
          {config.label}
        </div>
        <div
          style={{
            fontFamily: FONT_SANS,
            fontSize: 23,
            fontWeight: 600,
            color: THEME.navy,
            lineHeight: 1.45,
          }}
        >
          {text}
        </div>
      </div>
    </div>
  );
};

const FramedImageCard: React.FC<{
  imagePath: string;
  caption?: string;
  spotlights?: SpotlightRect[];
  height?: number;
}> = ({ imagePath, caption, spotlights, height = 640 }) => {
  const frame = useCurrentFrame();
  const cardOpacity = interpolate(frame, [4, 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const primarySp = spotlights && spotlights.length > 0 ? spotlights[0] : null;
  const zoom = primarySp
    ? interpolate(frame, [0, 42, 75], [1, 1, 1.36], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.bezier(0.16, 1, 0.3, 1),
      })
    : interpolate(frame, [0, 240], [1, 1.02], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
  const originX = primarySp
    ? Math.min(92, Math.max(8, primarySp.x + (primarySp.w ?? 10) / 2))
    : 50;
  const originY = primarySp
    ? Math.min(92, Math.max(8, primarySp.y + (primarySp.h ?? 10) / 2))
    : 50;

  return (
    <div
      style={{
        opacity: cardOpacity,
        backgroundColor: "#FFFFFF",
        borderRadius: 18,
        border: `2px solid ${THEME.cardBorder}`,
        boxShadow: "0 16px 40px rgba(15, 23, 42, 0.08)",
        padding: 8,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        width: "100%",
      }}
    >
      <div
        style={{
          position: "relative",
          width: "100%",
          height,
          borderRadius: 12,
          overflow: "hidden",
          backgroundColor: "#FFFFFF",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Img
          src={staticFile(resolveAssetPath(imagePath))}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "contain",
            transform: `scale(${zoom})`,
            transformOrigin: `${originX}% ${originY}%`,
          }}
        />
        {(spotlights ?? []).map((sp, idx) => {
          const spStart = 16 + idx * 12;
          const spO = interpolate(frame, [spStart, spStart + 12], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const pulse = 1 + Math.sin((frame - spStart) * 0.16) * 0.02;
          if (!sp.label) return null;
          const displayLabel =
            sp.label === "ここをクリック" || sp.label === "1. 新規登録"
              ? "右上の赤丸「無料で新規登録」"
              : sp.label;
          return (
            <div
              key={idx}
              style={{
                position: "absolute",
                top: 12 + idx * 46,
                left: 12,
                backgroundColor: sp.color ?? "#DC2626",
                color: "#FFFFFF",
                fontFamily: FONT_ROUND,
                fontWeight: 800,
                fontSize: 20,
                padding: "7px 16px",
                borderRadius: 999,
                boxShadow: "0 8px 20px rgba(15, 23, 42, 0.25)",
                border: "2px solid #FFFFFF",
                opacity: spO,
                transform: `scale(${pulse})`,
                pointerEvents: "none",
              }}
            >
              🔍 {displayLabel}
            </div>
          );
        })}
      </div>
      {caption && (
        <div
          style={{
            fontFamily: FONT_SANS,
            fontSize: 18,
            color: THEME.muted,
            marginTop: 6,
            textAlign: "center",
            lineHeight: 1.35,
          }}
        >
          {caption}
        </div>
      )}
    </div>
  );
};

// 1. Title / Goal Scene
const TitleSceneView: React.FC<{ s: Lesson01Scene; build: Lesson01Build }> = ({
  s,
  build,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const sp = spring({ frame, fps, config: { damping: 200 } });

  return (
    <AbsoluteFill
      style={{
        padding: "88px 100px 150px 100px",
        flexDirection: "row",
        alignItems: "center",
        gap: 56,
      }}
    >
      <div style={{ flex: s.image ? "0 0 56%" : "1 1 100%" }}>
        <AnimatedBadge
          text={`${build.videoType} ｜ ${s.badge ?? "はじめてのAI"}`}
          color={s.badgeColor ?? "blue"}
        />
        <div
          style={{
            fontFamily: FONT_ROUND,
            fontWeight: 900,
            fontSize: 58,
            color: THEME.navy,
            lineHeight: 1.22,
            marginTop: 8,
            opacity: sp,
            transform: `translateY(${interpolate(sp, [0, 1], [24, 0])}px)`,
          }}
        >
          <HighlightMarker>{s.heading}</HighlightMarker>
        </div>
        {s.sub && (
          <div
            style={{
              fontFamily: FONT_SANS,
              fontSize: 28,
              fontWeight: 600,
              color: THEME.blue,
              marginTop: 14,
            }}
          >
            {s.sub}
          </div>
        )}
        {(s.bullets ?? []).length > 0 && (
          <div
            style={{
              marginTop: 28,
              backgroundColor: "#FFFFFF",
              borderRadius: 20,
              border: `2px solid ${THEME.blueBorder}`,
              padding: "24px 30px",
              boxShadow: "0 12px 32px rgba(37, 99, 235, 0.07)",
            }}
          >
            {(s.bullets ?? []).map((b, i) => {
              const start = 14 + i * 10;
              const o = interpolate(frame, [start, start + 12], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              });
              const x = interpolate(frame, [start, start + 12], [28, 0], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: Easing.bezier(0.16, 1, 0.3, 1),
              });
              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 16,
                    opacity: o,
                    transform: `translateX(${x}px)`,
                    marginBottom: i === (s.bullets?.length ?? 0) - 1 ? 0 : 16,
                  }}
                >
                  <div
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: 999,
                      backgroundColor: THEME.blue,
                      color: "#FFFFFF",
                      fontFamily: FONT_ROUND,
                      fontWeight: 800,
                      fontSize: 20,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                    }}
                  >
                    ✓
                  </div>
                  <div
                    style={{
                      fontFamily: FONT_SANS,
                      fontSize: 26,
                      fontWeight: 700,
                      color: THEME.navy,
                      lineHeight: 1.4,
                    }}
                  >
                    {b}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {s.tip && <CalloutBox type="tip" text={s.tip} delay={36} />}
      </div>
      {s.image && (
        <div style={{ flex: "0 0 40%" }}>
          <FramedImageCard
            imagePath={s.image}
            caption={s.imageCaption}
            spotlights={s.spotlights}
            height={480}
          />
        </div>
      )}
    </AbsoluteFill>
  );
};

// 1b. Full Image Hero Scene (100% Display Area Rule for Textbook Diagrams/Screenshots)
const FullImageSceneView: React.FC<{ s: Lesson01Scene }> = ({ s }) => {
  const hasCallout = Boolean(s.tip || s.warning || s.quote);
  return (
    <AbsoluteFill
      style={{
        padding: "72px 48px 126px 48px",
        flexDirection: "column",
        justifyContent: "space-between",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 20,
          marginBottom: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {s.badge && (
            <div style={{ marginBottom: -14 }}>
              <AnimatedBadge text={s.badge} color={s.badgeColor} />
            </div>
          )}
          <div
            style={{
              fontFamily: FONT_ROUND,
              fontWeight: 800,
              fontSize: 38,
              color: THEME.navy,
              lineHeight: 1.2,
            }}
          >
            <HighlightMarker>{s.heading}</HighlightMarker>
          </div>
        </div>
        {s.sub && (
          <div
            style={{
              fontFamily: FONT_SANS,
              fontSize: 21,
              fontWeight: 600,
              color: THEME.slate,
            }}
          >
            {s.sub}
          </div>
        )}
      </div>

      {s.image && (
        <div style={{ width: "100%", flex: 1, display: "flex", alignItems: "center" }}>
          <FramedImageCard
            imagePath={s.image}
            caption={s.imageCaption}
            spotlights={s.spotlights}
            height={hasCallout ? 650 : 735}
          />
        </div>
      )}

      {s.quote && <CalloutBox type="quote" text={s.quote} delay={22} />}
      {s.tip && <CalloutBox type="tip" text={s.tip} delay={22} />}
      {s.warning && <CalloutBox type="warning" text={s.warning} delay={22} />}
    </AbsoluteFill>
  );
};

// 2. Split Image + Points / Steps Scene
const SplitImageSceneView: React.FC<{ s: Lesson01Scene }> = ({ s }) => {
  const frame = useCurrentFrame();
  const hasImage = Boolean(s.image);

  return (
    <AbsoluteFill
      style={{
        padding: "76px 52px 132px 52px",
        flexDirection: "row",
        alignItems: "center",
        gap: 32,
      }}
    >
      <div style={{ flex: hasImage ? "0 0 40%" : "1 1 100%" }}>
        <SectionHeading
          badge={s.badge}
          badgeColor={s.badgeColor}
          heading={s.heading}
          sub={s.sub}
        />

        {(s.steps ?? []).map((st, i) => {
          const start = 12 + i * 12;
          const o = interpolate(frame, [start, start + 12], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const x = interpolate(frame, [start, start + 12], [24, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          return (
            <div
              key={i}
              style={{
                opacity: o,
                transform: `translateX(${x}px)`,
                backgroundColor: "#FFFFFF",
                borderRadius: 16,
                border: `2px solid ${THEME.cardBorder}`,
                padding: "14px 20px",
                marginBottom: 12,
                display: "flex",
                alignItems: "flex-start",
                gap: 16,
                boxShadow: "0 6px 20px rgba(15, 23, 42, 0.04)",
              }}
            >
              <div
                style={{
                  backgroundColor: THEME.blue,
                  color: "#FFFFFF",
                  fontFamily: FONT_ROUND,
                  fontWeight: 800,
                  fontSize: 20,
                  padding: "4px 12px",
                  borderRadius: 10,
                  flexShrink: 0,
                  marginTop: 2,
                }}
              >
                {st.num}
              </div>
              <div style={{ flex: 1 }}>
                <div
                  style={{
                    fontFamily: FONT_ROUND,
                    fontWeight: 800,
                    fontSize: 24,
                    color: THEME.navy,
                  }}
                >
                  {st.title}
                </div>
                <div
                  style={{
                    fontFamily: FONT_SANS,
                    fontSize: 21,
                    color: THEME.slate,
                    marginTop: 4,
                    lineHeight: 1.4,
                  }}
                >
                  {st.desc}
                </div>
              </div>
            </div>
          );
        })}

        {(s.bullets ?? []).map((b, i) => {
          const start = 14 + i * 10;
          const o = interpolate(frame, [start, start + 12], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          return (
            <div
              key={i}
              style={{
                opacity: o,
                display: "flex",
                alignItems: "flex-start",
                gap: 14,
                marginBottom: 14,
                backgroundColor: "#FFFFFF",
                padding: "13px 18px",
                borderRadius: 14,
                border: `1px solid ${THEME.cardBorder}`,
              }}
            >
              <span
                style={{
                  color: THEME.blue,
                  fontSize: 26,
                  fontWeight: 900,
                  lineHeight: 1.2,
                }}
              >
                ●
              </span>
              <span
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 23,
                  fontWeight: 600,
                  color: THEME.navy,
                  lineHeight: 1.4,
                }}
              >
                {b}
              </span>
            </div>
          );
        })}

        {s.quote && <CalloutBox type="quote" text={s.quote} delay={28} />}
        {s.tip && <CalloutBox type="tip" text={s.tip} delay={30} />}
        {s.warning && (
          <CalloutBox type="warning" text={s.warning} delay={32} />
        )}
      </div>

      {s.image && (
        <div style={{ flex: "0 0 58%" }}>
          <FramedImageCard
            imagePath={s.image}
            caption={s.imageCaption}
            spotlights={s.spotlights}
            height={650}
          />
        </div>
      )}
    </AbsoluteFill>
  );
};

// 3. Dual Image Scene (e.g. Step 1 & Step 2 side by side)
const DualImageSceneView: React.FC<{ s: Lesson01Scene }> = ({ s }) => {
  return (
    <AbsoluteFill
      style={{
        padding: "74px 48px 130px 48px",
        flexDirection: "column",
      }}
    >
      <SectionHeading
        badge={s.badge}
        badgeColor={s.badgeColor}
        heading={s.heading}
        sub={s.sub}
      />
      <div
        style={{
          display: "flex",
          gap: 24,
          flex: 1,
          alignItems: "stretch",
        }}
      >
        {s.image && (
          <div style={{ flex: "1 1 56%" }}>
            <FramedImageCard
              imagePath={s.image}
              caption={s.imageCaption}
              spotlights={s.spotlights}
              height={540}
            />
          </div>
        )}
        {s.secondImage && (
          <div style={{ flex: "1 1 44%" }}>
            <FramedImageCard
              imagePath={s.secondImage}
              caption={s.secondImageCaption}
              height={540}
            />
          </div>
        )}
      </div>
      {s.tip && <CalloutBox type="tip" text={s.tip} delay={24} />}
    </AbsoluteFill>
  );
};

// 4. Structured Table Scene (with optional side image)
const TableSceneView: React.FC<{ s: Lesson01Scene }> = ({ s }) => {
  const frame = useCurrentFrame();
  const table = s.table ?? { headers: [], rows: [] };
  const hasImage = Boolean(s.image);

  return (
    <AbsoluteFill
      style={{
        padding: "76px 52px 132px 52px",
        flexDirection: "row",
        alignItems: "center",
        gap: 32,
      }}
    >
      <div style={{ flex: hasImage ? "0 0 48%" : "1 1 100%" }}>
        <SectionHeading
          badge={s.badge}
          badgeColor={s.badgeColor}
          heading={s.heading}
          sub={s.sub}
        />

        <div
          style={{
            backgroundColor: "#FFFFFF",
            borderRadius: 20,
            overflow: "hidden",
            border: `2px solid ${THEME.cardBorder}`,
            boxShadow: "0 14px 36px rgba(15, 23, 42, 0.06)",
          }}
        >
          {/* Header */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                table.headers.length === 2
                  ? "1.1fr 2.2fr"
                  : table.headers.length === 3
                    ? "1fr 1.4fr 1.4fr"
                    : "0.7fr 1.1fr 1.8fr 1.2fr",
              backgroundColor: THEME.navy,
              color: "#FFFFFF",
              padding: "14px 22px",
              fontFamily: FONT_ROUND,
              fontWeight: 800,
              fontSize: 22,
              gap: 16,
            }}
          >
            {table.headers.map((h, idx) => (
              <div key={idx}>{h}</div>
            ))}
          </div>

          {/* Rows */}
          {table.rows.map((row, rIdx) => {
            const start = 10 + rIdx * 9;
            const o = interpolate(frame, [start, start + 12], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <div
                key={rIdx}
                style={{
                  opacity: o,
                  display: "grid",
                  gridTemplateColumns:
                    table.headers.length === 2
                      ? "1.1fr 2.2fr"
                      : table.headers.length === 3
                        ? "1fr 1.4fr 1.4fr"
                        : "0.7fr 1.1fr 1.8fr 1.2fr",
                  padding: "13px 22px",
                  borderTop: `1px solid ${THEME.cardBorder}`,
                  backgroundColor: rIdx % 2 === 0 ? "#FFFFFF" : "#F8FAFC",
                  fontFamily: FONT_SANS,
                  fontSize: 21,
                  color: THEME.navy,
                  gap: 16,
                  alignItems: "center",
                }}
              >
                {row.map((cell, cIdx) => (
                  <div
                    key={cIdx}
                    style={{
                      fontWeight: cIdx === 0 ? 800 : 500,
                      color:
                        cIdx === 0
                          ? THEME.blue
                          : cIdx === table.highlightCol
                            ? THEME.navy
                            : THEME.slate,
                      lineHeight: 1.38,
                    }}
                  >
                    {cell}
                  </div>
                ))}
              </div>
            );
          })}
        </div>

        {s.tip && <CalloutBox type="tip" text={s.tip} delay={30} />}
        {s.warning && (
          <CalloutBox type="warning" text={s.warning} delay={30} />
        )}
      </div>

      {hasImage && s.image && (
        <div style={{ flex: "0 0 50%" }}>
          <FramedImageCard
            imagePath={s.image}
            caption={s.imageCaption}
            spotlights={s.spotlights}
            height={620}
          />
        </div>
      )}
    </AbsoluteFill>
  );
};

// 5. Chat Simulation Scene (Step-by-step prompts)
const ChatSimSceneView: React.FC<{ s: Lesson01Scene }> = ({ s }) => {
  const frame = useCurrentFrame();
  const steps = s.chatSteps ?? [];

  return (
    <AbsoluteFill
      style={{
        padding: "84px 92px 150px 92px",
        flexDirection: "column",
      }}
    >
      <SectionHeading
        badge={s.badge}
        badgeColor={s.badgeColor}
        heading={s.heading}
        sub={s.sub}
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns:
            steps.length === 1 ? "1fr" : "repeat(3, minmax(0, 1fr))",
          gap: 24,
          marginTop: 6,
        }}
      >
        {steps.map((cs, i) => {
          const start = 12 + i * 16;
          const o = interpolate(frame, [start, start + 14], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const y = interpolate(frame, [start, start + 14], [24, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          });
          return (
            <div
              key={i}
              style={{
                opacity: o,
                transform: `translateY(${y}px)`,
                backgroundColor: "#FFFFFF",
                borderRadius: 20,
                border: `2px solid ${THEME.blueBorder}`,
                padding: 24,
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                boxShadow: "0 12px 30px rgba(37, 99, 235, 0.07)",
              }}
            >
              <div>
                <div
                  style={{
                    display: "inline-block",
                    backgroundColor: THEME.blue,
                    color: "#FFFFFF",
                    fontFamily: FONT_ROUND,
                    fontWeight: 800,
                    fontSize: 19,
                    padding: "5px 14px",
                    borderRadius: 999,
                    marginBottom: 12,
                  }}
                >
                  {cs.stepLabel}
                </div>
                <div
                  style={{
                    fontFamily: FONT_ROUND,
                    fontWeight: 800,
                    fontSize: 25,
                    color: THEME.navy,
                    marginBottom: 14,
                    lineHeight: 1.35,
                  }}
                >
                  {cs.title}
                </div>
                <div
                  style={{
                    backgroundColor: "#0F172A",
                    color: "#F8FAFC",
                    fontFamily: FONT_MONO,
                    fontSize: 22,
                    lineHeight: 1.55,
                    padding: "18px 20px",
                    borderRadius: 14,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {cs.prompt}
                </div>
              </div>
              {cs.note && (
                <div
                  style={{
                    fontFamily: FONT_SANS,
                    fontSize: 20,
                    color: THEME.slate,
                    marginTop: 14,
                    lineHeight: 1.4,
                  }}
                >
                  {cs.note}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {s.tip && <CalloutBox type="tip" text={s.tip} delay={36} />}
    </AbsoluteFill>
  );
};

// 6. Safety Promises Scene (3 Promises)
const PromisesSceneView: React.FC<{ s: Lesson01Scene }> = ({ s }) => {
  const frame = useCurrentFrame();
  const steps = s.steps ?? [];

  return (
    <AbsoluteFill
      style={{
        padding: "84px 92px 150px 92px",
        flexDirection: "column",
      }}
    >
      <SectionHeading
        badge={s.badge}
        badgeColor={s.badgeColor ?? "red"}
        heading={s.heading}
        sub={s.sub}
      />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 26,
          marginTop: 8,
        }}
      >
        {steps.map((st, i) => {
          const start = 12 + i * 14;
          const o = interpolate(frame, [start, start + 14], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const y = interpolate(frame, [start, start + 14], [24, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const colors = [THEME.red, THEME.blue, THEME.green];
          const bgs = [THEME.redLight, THEME.blueLight, THEME.greenLight];
          return (
            <div
              key={i}
              style={{
                opacity: o,
                transform: `translateY(${y}px)`,
                backgroundColor: "#FFFFFF",
                borderRadius: 22,
                border: `2px solid ${THEME.cardBorder}`,
                borderTop: `8px solid ${colors[i % 3]}`,
                padding: 26,
                boxShadow: "0 14px 34px rgba(15, 23, 42, 0.06)",
              }}
            >
              <div
                style={{
                  display: "inline-block",
                  backgroundColor: bgs[i % 3],
                  color: colors[i % 3],
                  fontFamily: FONT_ROUND,
                  fontWeight: 900,
                  fontSize: 21,
                  padding: "6px 16px",
                  borderRadius: 999,
                  marginBottom: 14,
                }}
              >
                {st.num}
              </div>
              <div
                style={{
                  fontFamily: FONT_ROUND,
                  fontWeight: 800,
                  fontSize: 27,
                  color: THEME.navy,
                  marginBottom: 12,
                  lineHeight: 1.35,
                }}
              >
                {st.title}
              </div>
              <div
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 21,
                  color: THEME.slate,
                  lineHeight: 1.5,
                }}
              >
                {st.desc}
              </div>
            </div>
          );
        })}
      </div>
      {s.tip && <CalloutBox type="tip" text={s.tip} delay={38} />}
    </AbsoluteFill>
  );
};

// 7. Worksheet & Checklist Scene
const WorksheetSceneView: React.FC<{ s: Lesson01Scene }> = ({ s }) => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill
      style={{
        padding: "84px 92px 150px 92px",
        flexDirection: "row",
        gap: 44,
        alignItems: "center",
      }}
    >
      <div style={{ flex: "0 0 52%" }}>
        <SectionHeading
          badge={s.badge}
          badgeColor={s.badgeColor ?? "green"}
          heading={s.heading}
          sub={s.sub}
        />
        <div
          style={{
            backgroundColor: "#FFFFFF",
            borderRadius: 20,
            border: `2px solid ${THEME.blueBorder}`,
            padding: "24px 28px",
            boxShadow: "0 12px 32px rgba(15, 23, 42, 0.06)",
          }}
        >
          <div
            style={{
              fontFamily: FONT_ROUND,
              fontWeight: 800,
              fontSize: 24,
              color: THEME.blue,
              marginBottom: 14,
            }}
          >
            【はじめてのAI体験シート】記入項目
          </div>
          {(s.worksheetItems ?? []).map((item, i) => {
            const start = 10 + i * 7;
            const o = interpolate(frame, [start, start + 10], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <div
                key={i}
                style={{
                  opacity: o,
                  fontFamily: FONT_SANS,
                  fontSize: 22,
                  fontWeight: 600,
                  color: THEME.navy,
                  padding: "8px 0",
                  borderBottom:
                    i === (s.worksheetItems?.length ?? 0) - 1
                      ? "none"
                      : `1px dashed ${THEME.cardBorder}`,
                }}
              >
                {item}
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ flex: "0 0 44%" }}>
        <div
          style={{
            backgroundColor: "#0F172A",
            borderRadius: 22,
            padding: "28px 30px",
            color: "#FFFFFF",
            boxShadow: "0 20px 44px rgba(15, 23, 42, 0.18)",
          }}
        >
          <div
            style={{
              fontFamily: FONT_ROUND,
              fontWeight: 800,
              fontSize: 26,
              color: "#FBBF24",
              marginBottom: 20,
            }}
          >
            ✓ できたことを確認しよう
          </div>
          {(s.checklist ?? []).map((ck, i) => {
            const start = 20 + i * 12;
            const o = interpolate(frame, [start, start + 12], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <div
                key={i}
                style={{
                  opacity: o,
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  backgroundColor: "rgba(255,255,255,0.08)",
                  padding: "14px 18px",
                  borderRadius: 14,
                  marginBottom: 12,
                  borderLeft: "5px solid #34D399",
                }}
              >
                <span style={{ color: "#34D399", fontSize: 26, fontWeight: 900 }}>
                  ✓
                </span>
                <span
                  style={{
                    fontFamily: FONT_SANS,
                    fontSize: 22,
                    fontWeight: 600,
                    lineHeight: 1.4,
                  }}
                >
                  {ck}
                </span>
              </div>
            );
          })}
        </div>
        {s.tip && <CalloutBox type="tip" text={s.tip} delay={40} />}
      </div>
    </AbsoluteFill>
  );
};

// 8. Dot Feature Flow Scene (with Full/Large Diagram Support for lesson01-13)
const DotFlowSceneView: React.FC<{ s: Lesson01Scene }> = ({ s }) => {
  const frame = useCurrentFrame();
  const steps = s.steps ?? [];
  const hasImage = Boolean(s.image);

  return (
    <AbsoluteFill
      style={{
        padding: "74px 48px 130px 48px",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
        }}
      >
        <SectionHeading
          badge={s.badge ?? "機能の紹介"}
          badgeColor={s.badgeColor ?? "purple"}
          heading={s.heading}
          sub={s.sub}
        />
        <div
          style={{
            backgroundColor: THEME.purpleLight,
            border: `2px solid ${THEME.purpleBorder}`,
            color: THEME.purple,
            fontFamily: FONT_ROUND,
            fontWeight: 800,
            fontSize: 19,
            padding: "8px 18px",
            borderRadius: 12,
          }}
        >
          ※流れのイメージ図（概念紹介）
        </div>
      </div>

      {hasImage && s.image && (
        <div style={{ marginBottom: 14 }}>
          <FramedImageCard
            imagePath={s.image}
            caption={s.imageCaption}
            spotlights={s.spotlights}
            height={steps.length > 0 ? 450 : 660}
          />
        </div>
      )}

      {steps.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns:
              steps.length === 2
                ? "repeat(2, minmax(0, 1fr))"
                : "repeat(4, minmax(0, 1fr))",
            gap: 18,
            marginTop: hasImage ? 0 : 6,
          }}
        >
          {steps.map((st, i) => {
            const start = 10 + i * 14;
            const o = interpolate(frame, [start, start + 14], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            const y = interpolate(frame, [start, start + 14], [24, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <div
                key={i}
                style={{
                  opacity: o,
                  transform: `translateY(${y}px)`,
                  backgroundColor: "#FFFFFF",
                  borderRadius: 18,
                  border: `2px solid ${THEME.purpleBorder}`,
                  padding: hasImage ? "14px 18px" : 24,
                  boxShadow: "0 12px 30px rgba(124, 58, 237, 0.08)",
                  display: "flex",
                  flexDirection: "column",
                }}
              >
                <div
                  style={{
                    display: "inline-block",
                    alignSelf: "flex-start",
                    backgroundColor: THEME.purple,
                    color: "#FFFFFF",
                    fontFamily: FONT_ROUND,
                    fontWeight: 800,
                    fontSize: hasImage ? 17 : 19,
                    padding: "4px 12px",
                    borderRadius: 999,
                    marginBottom: hasImage ? 8 : 14,
                  }}
                >
                  {st.num}
                </div>
                <div
                  style={{
                    fontFamily: FONT_ROUND,
                    fontWeight: 800,
                    fontSize: hasImage ? 22 : 25,
                    color: THEME.navy,
                    marginBottom: 6,
                    lineHeight: 1.3,
                  }}
                >
                  {st.title}
                </div>
                <div
                  style={{
                    fontFamily: FONT_SANS,
                    fontSize: hasImage ? 19 : 21,
                    color: THEME.slate,
                    lineHeight: 1.45,
                  }}
                >
                  {st.desc}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {!hasImage && steps.length === 2 && (
        <div
          style={{
            marginTop: 18,
            backgroundColor: "#0F172A",
            borderRadius: 18,
            padding: "16px 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 20,
            opacity: interpolate(frame, [24, 38], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          }}
        >
          <div
            style={{
              fontFamily: FONT_ROUND,
              fontWeight: 800,
              fontSize: 21,
              color: "#C4B5FD",
              flexShrink: 0,
            }}
          >
            📚 例「読書会の準備」でまとまる3つの資料：
          </div>
          <div style={{ display: "flex", gap: 16, flex: 1 }}>
            {[
              { icon: "✉️", label: "案内文（お知らせ）" },
              { icon: "📋", label: "当日の進行案" },
              { icon: "🎒", label: "持ち物リスト" },
            ].map((d, idx) => (
              <div
                key={idx}
                style={{
                  flex: 1,
                  backgroundColor: "rgba(255,255,255,0.10)",
                  border: "1px solid rgba(196, 181, 253, 0.35)",
                  borderRadius: 12,
                  padding: "10px 16px",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  color: "#FFFFFF",
                  fontFamily: FONT_ROUND,
                  fontWeight: 700,
                  fontSize: 20,
                }}
              >
                <span>{d.icon}</span>
                <span>{d.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {s.tip && <CalloutBox type="tip" text={s.tip} delay={34} />}
      {s.quote && <CalloutBox type="quote" text={s.quote} delay={36} />}
    </AbsoluteFill>
  );
};

// Synchronized Bottom Subtitle (Telop) Bar
const SubtitleBar: React.FC<{ narration: string; durationInFrames: number }> = ({
  narration,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const sentences = narration
    .split(/(?<=[。！？])\s*/)
    .map((x) => x.trim())
    .filter(Boolean);

  if (sentences.length === 0) return null;

  const totalChars = sentences.reduce((acc, s) => acc + s.length, 0) || 1;
  let accum = 0;
  let activeSentence = sentences[sentences.length - 1];

  for (const s of sentences) {
    const startRatio = accum / totalChars;
    accum += s.length;
    const endRatio = accum / totalChars;
    const startF = Math.floor(startRatio * durationInFrames);
    const endF = Math.ceil(endRatio * durationInFrames);
    if (frame >= startF && frame <= endF) {
      activeSentence = s;
      break;
    }
  }

  return (
    <div
      style={{
        position: "absolute",
        left: 90,
        right: 90,
        bottom: 24,
        display: "flex",
        justifyContent: "center",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          backgroundColor: "rgba(15, 23, 42, 0.90)",
          color: "#FFFFFF",
          fontFamily: FONT_ROUND,
          fontWeight: 700,
          fontSize: 27,
          lineHeight: 1.4,
          padding: "14px 34px",
          borderRadius: 16,
          textAlign: "center",
          maxWidth: 1680,
          boxShadow: "0 10px 28px rgba(0, 0, 0, 0.25)",
          border: "1px solid rgba(255, 255, 255, 0.15)",
        }}
      >
        {activeSentence}
      </div>
    </div>
  );
};

const SceneRenderer: React.FC<{ s: Lesson01Scene; build: Lesson01Build }> = ({
  s,
  build,
}) => {
  const frame = useCurrentFrame();
  // Smooth cross-fade in & out per scene
  const opacity = interpolate(
    frame,
    [0, 10, Math.max(12, s.frames - 10), s.frames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <AbsoluteFill style={{ opacity }}>
      {s.kind === "title" && <TitleSceneView s={s} build={build} />}
      {s.kind === "full-image" && <FullImageSceneView s={s} />}
      {s.kind === "split-image" && <SplitImageSceneView s={s} />}
      {s.kind === "dual-image" && <DualImageSceneView s={s} />}
      {s.kind === "table" && <TableSceneView s={s} />}
      {s.kind === "chat-sim" && <ChatSimSceneView s={s} />}
      {s.kind === "promises" && <PromisesSceneView s={s} />}
      {s.kind === "worksheet" && <WorksheetSceneView s={s} />}
      {s.kind === "dot-flow" && <DotFlowSceneView s={s} />}
      <SubtitleBar narration={s.narration} durationInFrames={s.frames} />
    </AbsoluteFill>
  );
};

export const Lesson01Video: React.FC<Lesson01Props> = ({ build }) => {
  const frame = useCurrentFrame();
  if (!build) {
    return null;
  }

  const progress = interpolate(frame, [0, build.totalFrames], [0, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const activeSceneIndex = build.scenes.findIndex(
    (s) => frame >= s.startFrame && frame < s.startFrame + s.frames,
  );
  const currentScene =
    build.scenes[activeSceneIndex >= 0 ? activeSceneIndex : 0];

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(135deg, ${THEME.bgStart} 0%, ${THEME.bgEnd} 100%)`,
      }}
    >
      {/* Decorative soft ambient circles */}
      <div
        style={{
          position: "absolute",
          top: -180,
          right: -120,
          width: 620,
          height: 620,
          borderRadius: "50%",
          background:
            "radial-gradient(circle, rgba(37,99,235,0.07) 0%, rgba(37,99,235,0) 70%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: -220,
          left: -140,
          width: 680,
          height: 680,
          borderRadius: "50%",
          background:
            "radial-gradient(circle, rgba(16,185,129,0.06) 0%, rgba(16,185,129,0) 70%)",
        }}
      />

      {/* Top Header Bar */}
      <div
        style={{
          position: "absolute",
          top: 24,
          left: 92,
          right: 92,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          zIndex: 10,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            fontFamily: FONT_ROUND,
            fontSize: 20,
            fontWeight: 700,
            color: THEME.slate,
          }}
        >
          <span
            style={{
              backgroundColor: THEME.navy,
              color: "#FFFFFF",
              padding: "4px 12px",
              borderRadius: 8,
              fontSize: 17,
            }}
          >
            {build.lessonId.toUpperCase()}
          </span>
          <span>{build.lessonTitle}</span>
        </div>
        <div
          style={{
            fontFamily: FONT_ROUND,
            fontSize: 19,
            fontWeight: 700,
            color: THEME.muted,
            backgroundColor: "#FFFFFF",
            padding: "6px 16px",
            borderRadius: 999,
            border: `1px solid ${THEME.cardBorder}`,
          }}
        >
          {currentScene?.sectionLabel ?? build.videoType} （
          {(activeSceneIndex >= 0 ? activeSceneIndex : 0) + 1} /{" "}
          {build.scenes.length}）
        </div>
      </div>

      {/* Scenes */}
      {build.scenes.map((s) => (
        <Sequence key={s.id} from={s.startFrame} durationInFrames={s.frames}>
          <SceneRenderer s={s} build={build} />
        </Sequence>
      ))}

      {/* Bottom Progress Bar */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: 8,
          backgroundColor: "#E2E8F0",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${progress}%`,
            backgroundColor: THEME.blue,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};
