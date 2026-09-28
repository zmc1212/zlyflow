import { expect, it } from 'vitest'
import { videoOptionVisible, sanitizeVideoOptionValues, type Director2VideoOptionField } from './director2-video-settings'

const fields: Director2VideoOptionField[] = [
  {name:'refine_enabled', ui_group:'advanced', definition:{label:'二采精修',type:'boolean',default:true}},
  {name:'refine_quality', ui_group:'advanced', definition:{label:'目标画质',type:'string',default:'2.0',enum:['1.0','2.0'],ui_visible_when:{refine_enabled:true}}},
]
it('shows target quality only for enabled refinement', () => {
  expect(videoOptionVisible(fields[1], {refine_enabled:'true'})).toBe(true)
  expect(videoOptionVisible(fields[1], {refine_enabled:'false'})).toBe(false)
})
it('filters legacy workflow settings without losing disabled state', () => {
  expect(sanitizeVideoOptionValues(fields,{speed:'balanced',weight_profile:'full',refine_enabled:'false',refine_quality:'4.0'}))
    .toEqual({refine_enabled:'false',refine_quality:'2.0'})
})
