"use client";

import { useEffect, useState } from "react";

import { Badge, Card, Input, PrimaryButton, SecondaryButton, SectionTitle, Textarea } from "@/components/ui";
import { api, SkillConfig } from "@/lib/api";

type SkillForm = {
  id?: string;
  name: string;
  description: string;
  content: string;
  enabled: boolean;
};

const emptySkill: SkillForm = {
  name: "",
  description: "",
  content: "",
  enabled: true
};

export default function SkillsPage() {
  const [skills, setSkills] = useState<SkillConfig[]>([]);
  const [form, setForm] = useState<SkillForm>(emptySkill);
  const [error, setError] = useState("");
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [zipName, setZipName] = useState("");
  const [zipDescription, setZipDescription] = useState("");

  async function loadAll() {
    const data = await api.get<SkillConfig[]>("/skills");
    setSkills(data);
  }

  useEffect(() => {
    loadAll().catch((err) => setError(err.message));
  }, []);

  async function saveSkill(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const payload = {
        name: form.name,
        description: form.description,
        content: form.content,
        source_type: "manual",
        enabled: form.enabled,
        builtin: false
      };
      if (form.id) await api.put(`/skills/${form.id}`, payload);
      else await api.post("/skills", payload);
      setForm(emptySkill);
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存 Skill 失败");
    }
  }

  /**
   * zip 上传入口用于批量导入 skill 包，后台会自动解压并抽取说明文件。
   */
  async function uploadZip(event: React.FormEvent) {
    event.preventDefault();
    if (!zipFile) {
      setError("请先选择 zip 压缩包");
      return;
    }
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", zipFile);
      if (zipName) formData.append("name", zipName);
      if (zipDescription) formData.append("description", zipDescription);
      formData.append("enabled", "true");
      await api.upload<SkillConfig>("/skills/upload-zip", formData);
      setZipFile(null);
      setZipName("");
      setZipDescription("");
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传 Skill zip 失败");
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
      <Card>
        <SectionTitle title="Skill 列表" desc="Skill 会在 Agent 创建/编辑时挂载，并注入到 Agent 的 system prompt。" />
        <div className="grid gap-3">
          {skills.map((skill) => (
            <div key={skill.id} className="rounded-2xl border border-[var(--line)] bg-[var(--panel-2)] p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <div className="font-medium text-[var(--text)]">{skill.name}</div>
                    <Badge tone={skill.enabled ? "success" : "warn"}>{skill.enabled ? "enabled" : "disabled"}</Badge>
                    <Badge>{skill.source_type}</Badge>
                  </div>
                  <div className="mt-1 text-sm text-[var(--muted)]">{skill.description}</div>
                  {skill.entry_file ? <div className="mt-2 text-xs text-[var(--muted)]">入口文件：{skill.entry_file}</div> : null}
                  {skill.package_path ? <div className="mt-1 break-all text-xs text-[var(--muted)]">包路径：{skill.package_path}</div> : null}
                  {skill.package_files?.length ? (
                    <details className="mt-3 rounded-xl border border-[var(--line)] bg-[var(--panel)] p-3">
                      <summary className="cursor-pointer text-sm font-medium text-[var(--text)]">查看压缩包文件树（{skill.package_files.length}）</summary>
                      <div className="mt-3 grid gap-1 text-xs text-[var(--muted)]">
                        {skill.package_files.map((file) => (
                          <div key={file} className="break-all">
                            {file}
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}
                  <details className="mt-3 rounded-xl border border-[var(--line)] bg-[var(--panel)] p-3">
                    <summary className="cursor-pointer text-sm font-medium text-[var(--text)]">查看 Skill 详情</summary>
                    <pre className="mt-3 whitespace-pre-wrap break-words text-xs text-[var(--muted)]">{skill.content}</pre>
                  </details>
                </div>
                <div className="flex gap-2">
                  <PrimaryButton
                    type="button"
                    onClick={() =>
                      setForm({
                        id: skill.id,
                        name: skill.name,
                        description: skill.description,
                        content: skill.content,
                        enabled: skill.enabled
                      })
                    }
                  >
                    编辑
                  </PrimaryButton>
                  <SecondaryButton
                    type="button"
                    onClick={async () => {
                      if (!window.confirm("确认删除这个 Skill 吗？")) return;
                      await api.del(`/skills/${skill.id}`);
                      await loadAll();
                    }}
                  >
                    删除
                  </SecondaryButton>
                </div>
              </div>
            </div>
          ))}
          {!skills.length ? <p className="text-sm text-[var(--muted)]">暂无 Skill。</p> : null}
        </div>
      </Card>

      <div className="grid gap-6">
        <Card>
          <SectionTitle title="上传 Skill 压缩包" desc="支持上传 zip，后台会自动解压并解析 SKILL.md / README.md / .md / .txt 文件。" />
          <form onSubmit={uploadZip} className="space-y-3">
            <input
              type="file"
              accept=".zip"
              onChange={(e) => setZipFile(e.target.files?.[0] ?? null)}
              className="block w-full rounded-xl border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)]"
            />
            <Input placeholder="可选：覆盖 Skill 名称" value={zipName} onChange={(e) => setZipName(e.target.value)} />
            <Input placeholder="可选：覆盖 Skill 描述" value={zipDescription} onChange={(e) => setZipDescription(e.target.value)} />
            <PrimaryButton type="submit">上传并解析 zip</PrimaryButton>
          </form>
        </Card>

        <Card>
          <SectionTitle title={form.id ? "编辑 Skill" : "创建 Skill"} desc="Skill 适合沉淀可复用提示片段、规则模板与领域知识。" />
          <form onSubmit={saveSkill} className="space-y-3">
            <Input placeholder="Skill 名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <Input placeholder="Skill 描述" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <Textarea placeholder="Skill 内容 / Prompt 片段" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} />
            <label className="flex items-center gap-2 text-sm text-[var(--text)]">
              <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
              启用 Skill
            </label>
            {error ? <p className="text-sm text-rose-500">{error}</p> : null}
            <div className="flex gap-3">
              <PrimaryButton type="submit">{form.id ? "保存 Skill" : "创建 Skill"}</PrimaryButton>
              {form.id ? (
                <SecondaryButton type="button" onClick={() => setForm(emptySkill)}>
                  取消
                </SecondaryButton>
              ) : null}
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
