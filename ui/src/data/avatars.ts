import type { AvatarMeta } from '../types';

export const RPM_DEFAULT_LIPSYNC = 0.45;

const VROID_DYNAMIC_BONES: unknown[] = [
  {
    bone: 'J_Sec_L_Bust1', type: 'point', stiffness: 400, damping: 10,
    deltaLocal: [0, 0.01, 0], deltaWorld: [0, -0.02, 0],
    limits: [[-0.01, 0.01], [-0.01, 0.01], [-0.01, 0.01], [-0.01, 0.01]],
  },
  {
    bone: 'J_Sec_R_Bust1', type: 'point', stiffness: 400, damping: 10,
    deltaLocal: [0, 0.01, 0], deltaWorld: [0, -0.02, 0],
    limits: [[-0.01, 0.01], [-0.01, 0.01], [-0.01, 0.01], [-0.01, 0.01]],
  },
  ...['Hair2_01', 'Hair3_01', 'Hair2_02', 'Hair3_02', 'Hair2_03', 'Hair3_03',
      'Hair2_04', 'Hair3_04', 'Hair2_05', 'Hair3_05'].map(s => ({
    bone: 'J_Sec_' + s,
    type: 'mix2',
    stiffness: s.startsWith('Hair2') ? 100 : 150,
    damping: 4,
    limits: [null, null, [null, 0.01], null],
  })),
  ...['Hair2_06', 'Hair3_06', 'Hair3_06_end', 'Hair2_07', 'Hair3_07', 'Hair3_07_end',
      'Hair2_08', 'Hair3_08', 'Hair4_08', 'Hair4_08_end', 'Hair2_09', 'Hair3_09',
      'Hair4_09', 'Hair4_09_end', 'Hair2_10', 'Hair3_10', 'Hair3_10_end',
      'Hair2_11', 'Hair3_11', 'Hair3_11_end'].map(s => ({
    bone: 'J_Sec_' + s,
    type: 'mix2',
    stiffness: s.startsWith('Hair2')
      ? 100
      : s.startsWith('Hair3')
        ? (s.endsWith('end') ? 200 : 150)
        : (s.endsWith('end') ? 200 : 150),
    damping: 4,
  })),
  { bone: 'J_Sec_Hair2_12', type: 'mix2', stiffness: 100, damping: 4, pivot: true },
  { bone: 'J_Sec_Hair3_12', type: 'mix2', stiffness: 150, damping: 4 },
  { bone: 'J_Sec_Hair2_13', type: 'mix2', stiffness: 100, damping: 4, pivot: true },
  { bone: 'J_Sec_Hair3_13', type: 'mix2', stiffness: 150, damping: 4 },
];

export const AVATARS: Record<string, AvatarMeta> = {
  vroid: {
    file: 'vroid.glb', category: 'a', body: 'F', label: 'Yuki (VRoid)',
    lipsyncScale: 2.8,
    baseline: { headRotateX: -0.1, eyeBlinkLeft: 0.05, eyeBlinkRight: 0.05 },
    modelDynamicBones: VROID_DYNAMIC_BONES,
  },

  // Names are display labels in the avatar picker rail. Keep them
  // friendly, internationally pronounceable, and varied — no two
  // should read as "the same person." The data-key (e.g. `brunette`,
  // `female-avatar1`) is what the agent.avatar_key references in the
  // DB, so renaming labels here is safe; renaming keys is not.
  brunette:         { file: 'brunette.glb',        category: 'w', body: 'F', label: 'Sofia' },
  'female-avatar1': { file: 'female-avatar1.glb',  category: 'w', body: 'F', label: 'Aria' },
  'female-avatar2': { file: 'female-avatar2.glb',  category: 'w', body: 'F', label: 'Maya' },
  'female-avatar3': { file: 'female-avatar3.glb',  category: 'w', body: 'F', label: 'Luna' },
  'female-avatar4': { file: 'female-avatar4.glb',  category: 'w', body: 'F', label: 'Layla' },
  'female-avatar5': { file: 'female-avatar5.glb',  category: 'w', body: 'F', label: 'Iris' },

  david:            { file: 'david.glb',           category: 'm', body: 'M', label: 'David' },
  avatar3:          { file: 'avatar3.glb',         category: 'm', body: 'M', label: 'Marcus' },
  'male-avatar1':   { file: 'male-avatar1.glb',    category: 'm', body: 'M', label: 'Leo' },
  'male-avatar2':   { file: 'male-avatar2.glb',    category: 'm', body: 'M', label: 'Ezra' },
  'male-avatar3':   { file: 'male-avatar3.glb',    category: 'm', body: 'M', label: 'Kai' },
  'male-avatar4':   { file: 'male-avatar4.glb',    category: 'm', body: 'M', label: 'Theo' },
  'male-avatar5':   { file: 'male-avatar5.glb',    category: 'm', body: 'M', label: 'Felix' },
  'male-avatar6':   { file: 'male-avatar6.glb',    category: 'm', body: 'M', label: 'Mateo' },
};

export const DEFAULT_AVATAR_KEY = 'brunette';

export function avatarUrl(avatar: AvatarMeta): string {
  return `/avatar-zoo/avatar-${avatar.category}/${avatar.file}`;
}

export const CATEGORY_LABEL: Record<AvatarMeta['category'], string> = {
  a: 'Anime',
  m: 'Male',
  w: 'Female',
};
