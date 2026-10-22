# garage — RSI 适配层（指针存根）

> **本文件的内容已并入 [`../docs/self-evolution.md`](../docs/self-evolution.md)**（自我进化总文档，2026-10-21 合并）。
>
> | 原内容 | 现在在哪 |
> |---|---|
> | A 线机制（四个席位、波次九步、guest 传输层、验证席隔离、内容围栏、合并七道闸、铺开闸与时延预检、DRS、记忆种子） | 总文档 **§2** |
> | A 线运行手册（前置条件、六条必跑 smoke、七个针对性 smoke、命令、Windows 与 POSIX 差异） | 总文档 **§5.5** |
> | 三层验收（L1 合并完整性 / L2 门禁 / L2.5 产线健康分 / L3 智能体面真验） | 总文档 **§5.5** |
> | 红线 | 总文档 **§5.5** |
> | 踩过的坑 | 总文档 **§5.3(c)**（含跨轮次方法论） |
>
> **仍然留在原处、且必须留在原处的东西**：
>
> - **装配契约 13 条（权威全文）** → [`run_usine.py`](run_usine.py) 模块 docstring。契约在代码里，次序承重；改文档不改编码等于没改。
> - **改进方向与护栏** → [`distribution-usine.md`](distribution-usine.md)。它是**引擎的输入**，不是文档。
> - **角色配置** → [`config/roles-usine/`](config/roles-usine/)（六个席位 yaml）与 [`config/spread.json`](config/spread.json)、[`config/spec-sync.json`](config/spec-sync.json)。
> - **fork 纪律** → [`../théâtre/PROVENANCE.md`](../théâtre/PROVENANCE.md)。
>
> 本文件保留为目录锚点。**不再有第二份说法**——要改运行手册，改总文档，然后回来同步这里的节号。
>
> 目录地图见 [`../docs/self-evolution.md`](../docs/self-evolution.md) §6。
