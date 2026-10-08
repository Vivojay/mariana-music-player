declare module '@strudel/repl'

declare module '@strudel/webaudio' {
  export function renderPatternAudio(
    pattern: unknown,
    cps: number,
    startCycle: number,
    endCycle: number,
    sampleRate: number,
    maxPolyphony: number,
    multiChannelOrbits: boolean,
    filename?: string,
  ): Promise<void>
}
