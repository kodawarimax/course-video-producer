import { Composition } from "remotion";
import { IntroScene } from "./scenes/IntroScene";
import { Tutorial, TOTAL_FRAMES } from "./scenes/tutorial/Tutorial";
import { M1_9, M1_9_TOTAL } from "./scenes/cca/M1_9";
import { CcaPreview, CCA_PREVIEW_TOTAL } from "./scenes/cca/CcaPreview";
import { LessonComp, type LessonBuild, type LessonProps } from "./scenes/cca/Lesson";
import {
  Lesson01Video,
  type Lesson01Build,
  type Lesson01Props,
} from "./scenes/lesson01/Lesson01Video";

const loadLessonBuild = async (id: unknown): Promise<LessonBuild> => {
  if (typeof id !== "string" || id.trim() === "") {
    throw new Error('Lesson render requires --props=\'{"id":"M1-9"}\'');
  }

  const lessonId = id.trim();
  if (!/^[A-Za-z0-9-]+$/.test(lessonId)) {
    throw new Error(`Invalid Lesson id: ${lessonId}`);
  }

  const mod = await import(`./scenes/cca/${lessonId}.build.json`);
  return (mod.default ?? mod) as LessonBuild;
};

const loadLesson01Build = async (id: string): Promise<Lesson01Build> => {
  const mod = await import(`./scenes/lesson01/${id}.build.json`);
  return (mod.default ?? mod) as Lesson01Build;
};

export const Root: React.FC = () => {
  return (
    <>
      {/* 縦型（SNS: TikTok / Instagram Reels / YouTube Shorts） */}
      <Composition
        id="IntroScene"
        component={IntroScene}
        durationInFrames={150}
        fps={30}
        width={1080}
        height={1920}
      />

      {/* 灯台ダッシュボード チュートリアル (横型 1080p / 2-3分) */}
      <Composition
        id="Tutorial"
        component={Tutorial}
        durationInFrames={TOTAL_FRAMES}
        fps={30}
        width={1920}
        height={1080}
      />

      {/* CCA講座 汎用レンダ: --props='{"id":"M1-9"}' で src/scenes/cca/<id>.build.json を読む */}
      <Composition
        id="Lesson"
        component={LessonComp}
        durationInFrames={1}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ id: "M1-9" } satisfies LessonProps}
        calculateMetadata={async ({ props }) => {
          const build = await loadLessonBuild(props.id);
          return {
            durationInFrames: build.totalFrames,
            fps: build.fps ?? 30,
            width: build.width ?? 1920,
            height: build.height ?? 1080,
            props: { ...props, id: build.id, build },
          };
        }}
      />

      {/* CCA講座 M1-9: プロンプトvs hooks (横型 1080p / データ駆動) */}
      <Composition
        id="M1-9"
        component={M1_9}
        durationInFrames={M1_9_TOTAL}
        fps={30}
        width={1920}
        height={1080}
      />

      {/* CCA講座 新レイアウト確認用: タイトル(鳥居)/本人紹介/経歴タイムライン */}
      <Composition
        id="CcaPreview"
        component={CcaPreview}
        durationInFrames={CCA_PREVIEW_TOTAL}
        fps={30}
        width={1920}
        height={1080}
      />

      {/* ai-user-a01 lesson01 動画制作パッケージ (batch.json jobs) */}
      {(["lesson01-full", "lesson01-06", "lesson01-13"] as const).map((jobId) => (
        <Composition
          key={jobId}
          id={jobId}
          component={Lesson01Video}
          durationInFrames={1}
          fps={30}
          width={1920}
          height={1080}
          defaultProps={{ id: jobId } satisfies Lesson01Props}
          calculateMetadata={async () => {
            const build = await loadLesson01Build(jobId);
            return {
              durationInFrames: build.totalFrames,
              fps: build.fps ?? 30,
              width: build.width ?? 1920,
              height: build.height ?? 1080,
              props: { id: jobId, build },
            };
          }}
        />
      ))}

      {/* 汎用コース動画レンダ: --props='/path/to/props.json' ({"build": ...}) または --props='{"id":"lesson01-full"}' */}
      <Composition
        id="CourseVideo"
        component={Lesson01Video}
        durationInFrames={1}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ id: "lesson01-full" } as Lesson01Props}
        calculateMetadata={async ({ props }) => {
          const typedProps = props as Lesson01Props;
          const build =
            typedProps.build ??
            (await loadLesson01Build(typedProps.id ?? "lesson01-full"));
          return {
            durationInFrames: build.totalFrames,
            fps: build.fps ?? 30,
            width: build.width ?? 1920,
            height: build.height ?? 1080,
            props: { id: build.id, build },
          };
        }}
      />
    </>
  );
};
