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
    language: 'ja', lipsyncScale: 2.8,
    baseline: { headRotateX: -0.1, eyeBlinkLeft: 0.05, eyeBlinkRight: 0.05 },
    modelDynamicBones: VROID_DYNAMIC_BONES,
  },

  brunette: { file: 'brunette.glb', category: 'w', body: 'F', label: 'Brunette' },
  'female-avatar1': { file: 'female-avatar1.glb', category: 'w', body: 'F', label: 'Female 1' },
  'female-avatar2': { file: 'female-avatar2.glb', category: 'w', body: 'F', label: 'Female 2' },
  'female-avatar3': { file: 'female-avatar3.glb', category: 'w', body: 'F', label: 'Female 3' },
  'female-avatar4': { file: 'female-avatar4.glb', category: 'w', body: 'F', label: 'Female 4' },
  'female-avatar5': { file: 'female-avatar5.glb', category: 'w', body: 'F', label: 'Female 5' },
  'p-f-a1': { file: 'p-f-a1.glb', category: 'w', body: 'F', label: 'Portrait 1' },
  'p-f-a2': { file: 'p-f-a2.glb', category: 'w', body: 'F', label: 'Portrait 2' },
  'p-m-a3': { file: 'p-m-a3.glb', category: 'w', body: 'F', label: 'Portrait 3' },
  'p-m-a4': { file: 'p-m-a4.glb', category: 'w', body: 'F', label: 'Portrait 4' },

  david: { file: 'david.glb', category: 'm', body: 'M', label: 'David' },
  avatarsdk: {
    file: 'avatarsdk.glb', category: 'm', body: 'M', label: 'Max (AvatarSDK)',
    lipsyncScale: 0.5,
    retarget: {
      Neck: { z: -0.01, rx: -0.15 },
      Neck1: { z: -0.01, rx: -0.15 },
      Neck2: { z: -0.01, rx: -0.15 },
      LeftShoulder: { rz: -0.3 },
      RightShoulder: { rz: 0.3 },
      scaleToEyesLevel: 1.0,
      origin: { y: -0.1 },
    },
    baseline: { headRotateX: -0.04, eyeBlinkLeft: 0.05, eyeBlinkRight: 0.05 },
  },
  avatar3: { file: 'avatar3.glb', category: 'm', body: 'M', label: 'Avatar 3' },
  'male-avatar1': { file: 'male-avatar1.glb', category: 'm', body: 'M', label: 'Male 1' },
  'male-avatar2': { file: 'male-avatar2.glb', category: 'm', body: 'M', label: 'Male 2' },
  'male-avatar3': { file: 'male-avatar3.glb', category: 'm', body: 'M', label: 'Male 3' },
  'male-avatar4': { file: 'male-avatar4.glb', category: 'm', body: 'M', label: 'Male 4' },
  'male-avatar5': { file: 'male-avatar5.glb', category: 'm', body: 'M', label: 'Male 5' },
  'male-avatar6': { file: 'male-avatar6.glb', category: 'm', body: 'M', label: 'Male 6' },
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
