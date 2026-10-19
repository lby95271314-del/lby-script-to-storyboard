# storyboard.json 数据约定

所有时间是秒，集内从0开始，段内也从0开始；用统一切点推导镜长，允许小数。JSON是交付数据，不是Seedance API请求体。资产ID不能直接充当平台附件引用。

最小结构如下（缩略画面内容仅示意，实际按11列补全）：

~~~json
{
  "project": {"title":"示例", "target_duration":5, "duration_mode":"content_first", "aspect_ratio":"16:9"},
  "characters":["甲"],
  "source_beats":[{"id":"B01", "text":"甲说话并交出钥匙", "source_location":"第一场"}],
  "source_dialogues":[{"id":"D01", "speaker":"甲", "text":"给你。"}],
  "assets":[{"id":"A01", "path":"assets/甲.png", "role":"character", "available":true}],
  "frames":[
    {"id":"F01", "kind":"lineart", "segment_id":"S01", "shot_id":"S01-01", "time":0, "status":"pending", "source_asset_ids":["A01"], "input_bound":false},
    {"id":"BOARD01", "kind":"board", "segment_id":"S01", "status":"pending"}
  ],
  "segments":[{
    "id":"S01", "start":0, "end":5, "board_id":"BOARD01",
    "shots":[{
      "id":"S01-01", "start":0, "end":5, "duration":5,
      "beat_ids":["B01"], "frame_ids":["F01"], "visible_characters":["甲"],
      "camera_id":"CAM1", "space":"甲画左，钥匙在桌面中部",
      "camera":{"scale":"中景","lens":"50mm等效","movement":"固定","depth":"中景深","composition":"甲居左","speed":"静止","angle":"平视"},
      "content":"甲看向画右的人，说完把钥匙推过去。",
      "dialogue_ids":["D01"],
      "events":[{"id":"E01","start":1,"end":2.5,"kind":"action","description":"推钥匙"}],
      "audio":{"ambience":"室内底噪","action":"钥匙轻擦桌面","human":"原台词","music":"无"},
      "previous_state":"甲持钥匙", "end_state":"钥匙停在桌面中部，甲松手"
    }],
    "utterances":[{
      "id":"U01", "source_id":"D01", "speaker":"甲", "text":"给你。",
      "part_start":0, "part_end":3, "mode":"sync", "start":0.5, "end":1.5,
      "shot_ids":["S01-01"], "lip_sync_shot_ids":["S01-01"],
      "timing_basis":"自然短句估算，未实测", "delivery":"平静"
    }],
    "prompt":"实际可复制的本段模型正文"
  }]
}
~~~

## 字段与对应关系

- characters为稳定说话人/人物名；source_beats保留原文节拍，shots.beat_ids认领，允许同一节拍跨镜。导演补充动作与原文分开标注。
- source_dialogues保存逐字原词。utterances描述真实声音区间；同句跨镜只写一条utterance，并列出所有相交镜头。跨生成段确有连续声轨方案时可以分片，part_start/part_end是原字符串的Unicode字符索引、左闭右开，各片拼回原句；不截断字音。增加continuity_plan说明后期/音频处理。
- utterances.mode为sync/vo/narration/inner/post，分别对应同步对白、画外声、旁白、内心声和后期配音。说话人始终明确，lip_sync_shot_ids只包含真正展示此人说话口型的镜头。重叠发声须记录overlap_reason，普通对白不默认重叠。
- 镜头和声音起止为段内相对时间，segment.start/end为集内时间。shots必须按剪辑顺序覆盖完整段；duration=end-start。叠化等特殊剪辑需要另存编辑时间轴并扩展检查，不能把重叠镜头直接塞进此线性约定。
- shots.events是镜内动作/表情/声音等时间区间，不是新增切镜；容许并行动作，顺序依赖可用depends_on记录。对白的单一权威时间放utterances，不在events复制另一套时间。
- camera七项逐项填写；audio四层逐项填写。HTML的11列从这些字段派生，台词列按ID引用完整原词与区间，台词核算列显示utterance的测量/估算依据。
- frames.kind为lineart、board、reference。lineart必须属于一个shot并有真实叙事时刻；关键帧用同一shot_id、不同time及可选keyframe_id。board属于segment。
- accepted帧必须给实际path；path相对于JSON所在目录或为绝对路径。记录真实dimensions、format、qa_notes、source_asset_ids及输入绑定信息。available只是资产可访问，input_bound是生成时实际传入；二者不能混同。
- 待出图可以用pending且无path；错误图用needs_fix并保留原因。setting/character参考只能kind=reference，不能挂到shots.frame_ids。
- prompt只存可复制模型正文；附件映射、计划时间条、音频连续方案、检查记录另存字段。

## 验证命令与边界

正式交付默认执行：

~~~text
python scripts/validate_storyboard.py 项目/storyboard.json --reviews 项目/visual-review.json
~~~

只有退出码0且delivery_allowed=true允许正式交付；未给视觉验收记录即拒绝。--require-media仍兼容但不绕过视觉门槛。明确的文字规划/进度草稿可用--draft，仅检查结构且delivery_allowed始终false，不允许夹带不合格截图。Python函数validate仍是结构检查，不代表正式交付许可。

每个叙事frame新增visual_contract，结构及九项逐图检查见[逐镜强制自检](visual-self-check.md)。有人进出画时frame.visible_characters单独说明该帧可见人物，否则继承整镜清单。board新增source_frame_ids及source_frames_sha256，顺序和源图哈希必须与通过验收的当前帧一致。

视觉验收单独存visual-review.json，含preflight/frames/boards，使用visual_gate.py prepare生成pending底稿；不可只手写accepted。图片、镜头目标或参考素材改变会使哈希绑定失效，需要重新验收。

数据检查本身不能理解图片内容；语义核对由真实看图的视觉能力/人工完成，程序强制检查记录完整、逐项通过、结构化人物观察与目标一致、文件与描述版本有效。不得虚构看图证据，完整记录区分结构检查、画面验收、网页检查和视频检查。
