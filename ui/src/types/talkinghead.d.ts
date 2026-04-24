export {};

declare global {
  interface TalkingHeadInstance {
    showAvatar(
      args: Record<string, unknown>,
      onProgress?: (ev: ProgressEvent) => void,
    ): Promise<void>;
    setMood(mood: string): void;
    setView(view: string): void;
    playGesture(name: string, duration?: number, mirror?: boolean, fade?: number): void;
    setPoseFromTemplate?(template: unknown, duration?: number): void;
    poseTemplates?: Record<string, unknown>;
    morphs?: Array<{
      morphTargetDictionary?: Record<string, number>;
      morphTargetInfluences?: number[];
    }>;
    stop?(): void;
    dispose?(): void;
  }

  interface TalkingHeadConstructor {
    new (container: HTMLElement, options: Record<string, unknown>): TalkingHeadInstance;
  }

  interface LipsyncEnInstance {
    wordsToVisemes(word: string): {
      words: string;
      visemes: string[];
      times: number[];
      durations: number[];
      i?: number;
    };
  }

  interface LipsyncEnConstructor {
    new (): LipsyncEnInstance;
  }

  interface Window {
    TalkingHead?: TalkingHeadConstructor;
    LipsyncEn?: LipsyncEnConstructor;
  }
}
