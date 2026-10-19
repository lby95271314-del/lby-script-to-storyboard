# 逐镜画面强制自检与交付门槛

## 两道门槛

用户要求：每镜画面内容、人物站位、构图须一致，不一致不能交付。尚未生成的图片无法预先验图，因此分开执行：

1. **生成前检查**：对照画面内容、空间位序、CAM/运镜七项、起止状态和指定截图时刻，先确定唯一、无矛盾的画面目标。内容说甲画左而空间表说甲画右时先修分镜，不调用生图工具。
2. **生成后检查**：实际打开生成图及相关原素材，逐项比对目标。合格才记accepted、放入正式截图/故事板/模型参考。失败或无法判断均阻止交付。

这不是“写一个已检查”标签。脚本不能独立理解像素；Codex须使用实际可用的看图工具/多模态视觉能力，或记录真实人工视觉复核，再由程序核对证据和阻止漏检。没有看图能力时保持pending，不得伪造通过记录。

## 先定义每张截图的画面目标

每个叙事frame新增visual_contract。目标从原镜头和该帧time推导，不能为了适配错图篡改原画面描述。起始帧、动作中间帧、结尾帧分开验收；静态截图只对其时刻负责，不要求一张图表现整段动作。

~~~json
{
  "narrative_moment":"段内0.0秒，甲尚未交出钥匙",
  "entities":{
    "甲":{"screen_side":"left","depth":"foreground","pose":"坐着","facing":"画右","gaze":"乙"},
    "乙":{"screen_side":"right","depth":"midground","pose":"站着","facing":"画左","gaze":"甲"}
  },
  "camera":"CAM1，平视中景；固定机位，甲膝上入画",
  "composition":"甲画左，乙画右；钥匙和两人手部可见；桌边在前景",
  "props":"钥匙在甲右手，乙未接触；不出现第二把钥匙",
  "scene":"门在后景右侧，窗光从画左进入；沿用对应场景素材"
}
~~~

screen_side取left/center/right/offscreen，均为当前摄影机画面坐标；depth、pose、facing、gaze用此镜明确的词汇。观察时按同一词汇填事实，相同语义可以沿用标签，实际不符必须写实际值，不能复制目标冒充观察。空镜entities可为{}，但文字中须明确空镜。有人进出画时，frame.visible_characters记录本时刻在画人物，必须属于shot.visible_characters；否则默认和整镜人物清单一致。

不要从世界坐标直接推画面左右。景别看实际取景范围，构图检查主体位置、裁切、占比、前后景和遮挡；不要求精确复现无法从线稿判断的焦距数值。

## 操作与证据文件

~~~text
python scripts/visual_gate.py prepare 项目/storyboard.json --reviews 项目/preflight-review.json
python scripts/visual_gate.py check 项目/storyboard.json --reviews 项目/preflight-review.json --phase preflight --shot-id S01-01
~~~

prepare只生成pending底稿和当前描述/素材哈希，绝不自动判通过，也不覆盖旧报告。阅读真实剧本与分镜，填preflight：text_inspected=true、reviewer、五项checks的expected/observed/status及verdict。五项为截图时刻明确、内容与站位一致、机位与构图一致、参考输入计划、承接状态一致。

**该镜generation_allowed=true后才能生成该镜候选图。** --shot-id只用于逐镜生成前检查；全套正式交付不能使用局部范围跳过坏镜。

生成结果先保存为候选文件。生成后再次prepare到新的visual-review.json以取得当前图片哈希，或计算实际文件SHA-256填入现有记录；仅当spec_sha256一致时可沿用真实完成的preflight。实际打开每一张候选图和身份/场景参考后填写frames记录：image_opened=true、reviewer、method=vision或human_visual、inspection_evidence（使用的看图工具/人工复核及所见细节），以及九项checks：

- narrative_moment：实际动作阶段符合截图时刻，不能把结尾姿态当起始帧。
- characters：人数、身份、服装/可见特征，额外人物和三视图克隆均不合格。
- positions：每人画面左右、前后层次，与该CAM投影一致。
- pose_gaze：站/坐/躺、身体朝向、视线/对视对象及表情。
- camera_scale_angle：景别、俯仰/平视、取景范围与可见空间。
- composition_occlusion：主体分布、过肩关系、裁切、遮挡与必要信息可见性。
- props_contact：道具归属、位置、左右手与接触、数量和动作状态。
- scene_light：门窗家具等锚点、光向、时段及连续性。
- narrative_source：是本镜叙事画面，真实使用了所需素材，不是设定板/裁切拼贴。

每项必须有非空expected、observed及status=pass，verdict也须pass；fail、uncertain、pending、缺项均不放行。观察事实同时写observed_entities，程序逐项比较人物身份和screen_side/depth/pose/facing/gaze，即使总体误填pass，左右或姿态字段不一致仍会拦截。不以总分/平均分抵消任何一项错误。不确定或遮挡导致必要信息不可见时标uncertain，调整构图或补帧后重审。

## 修图与故事板

发现不符时记needs_fix和具体差异，保留失败记录在工作目录的修正历史，针对错误改生成指令/参考输入，重新生成候选图并完整重验。不得改剧本、镜头描述或验收目标来迁就坏图；确需导演改稿时明确改稿，相关图全部重新验收。每张图常规最多两次修正后停止自动重试，交代阻塞项；停止重试不等于允许交付。

正式故事板只使用通过逐帧验收的图。board记录source_frame_ids（按段内镜头/关键帧顺序）及source_frames_sha256（ID到实际SHA-256的映射），以程序确认没有旧图、错图或未验图混入。实际打开排版导出的故事板PNG，填boards的narrative_cells、labels_timing、reference_separation三项视觉复核；同样绑定PNG哈希和实际看图证据。

所有声明在shot.frame_ids中的截图/关键帧都必须验收，不能一镜有一张好图就夹带另一张错图；失败尝试文件留在工作区，不放正式frames/、boards/、HTML或模型参考包。正式图包仅打包与通过门槛JSON对应的引用文件；完成HTML/PNG后实际打开检查，网页包装完成不代替图像验收。

## 正式交付命令

~~~text
python scripts/validate_storyboard.py 项目/storyboard.json --reviews 项目/visual-review.json
~~~

默认执行数据、所需媒体、全套逐镜视觉证据与故事板检查。退出码0且delivery_allowed=true才允许正式交付；任一镜失败、缺图、缺复核、无法判断、图片/描述/参考素材被改动、故事板用了旧图，均退出码1。

只有用户明确要求文字规划或进度草稿时可用--draft做结构检查；它始终delivery_allowed=false，不能通过草稿模式交付不合格截图，不能称为完成稿。镜头描述、visual_contract、相关源素材或图片一旦改变，哈希不同使旧记录自动失效。只复用描述、素材和图片哈希全部仍一致的真实验收。

程序核对的是验收记录、结构化观察事实及文件版本，无法防止人为伪造看图结论。执行者必须真实看图；通过记录不等于模型永不出错。交付检查表逐镜给出镜号/帧号、期望、实际观察、通过或失败、修正次数和当前文件，可在11列表外展开，不增改11列。

故事板复核还绑定spec_sha256：镜头时刻、机位、画面描述、源素材或来源列表发生变化，即使PNG暂未更换，也必须重新检查格子标注与布局，不沿用旧通过记录。

逐镜看图、记录观察、修正差异和执行门槛由运行本技能的Codex完成，不默认要求用户手填JSON或逐镜确认。必须检查最终实际图片，不能只检查生图提示词、文字描述或缩略占位图；没有视觉能力则报告阻塞，不伪造验收。
