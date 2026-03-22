"use client";

import { useEffect, useMemo, useState } from "react";

import { Badge, Card, CheckboxRow, EmptyState, Field, InlineAlert, Input, PrimaryButton, SecondaryButton, SectionTitle, Skeleton, Textarea, useToast } from "@/components/ui";
import { api, SkillConfig } from "@/lib/api";
import { focusField } from "@/lib/form-feedback";

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
  const { toast } = useToast();
  const [skills, setSkills] = useState<SkillConfig[]>([]);
  const [form, setForm] = useState<SkillForm>(emptySkill);
  const [error, setError] = useState("");
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [zipName, setZipName] = useState("");
  const [zipDescription, setZipDescription] = useState("");
  const [bootstrapping, setBootstrapping] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [busySkillId, setBusySkillId] = useState<string | null>(null);

  async function loadAll(showLoader = false) {
    if (showLoader) setBootstrapping(true);
    try {
      const data = await api.get<SkillConfig[]>("/skills");
      setSkills(data);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 Skill 列表失败");
    } finally {
      if (showLoader) setBootstrapping(false);
    }
  }

  useEffect(() => {
    void loadAll(true);
  }, []);

  const formErrors = useMemo(
    () => ({
      name: form.name.trim() ? "" : "请输入 Skill 名称",
      description: form.description.trim() ? "" : "请输入 Skill 描述",
      content: form.content.trim() ? "" : "请输入 Skill 内容"
    }),
    [form]
  );

  async function saveSkill(event: React.FormEvent) {
    event.preventDefault();
    const firstError = Object.entries(formErrors).find(([, value]) => value)?.[0];
    if (firstError) {
      focusField(firstError);
      return;
    }

    setSaving(true);
    setError("");
    try {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim(),
        content: form.content,
        source_type: "manual",
        enabled: form.enabled,
        builtin: false
      };
      if (form.id) await api.put(`/skills/${form.id}`, payload);
      else await api.post("/skills", payload);
      const skillName = form.name.trim();
      setForm(emptySkill);
      await loadAll();
      toast({ tone: "success", title: form.id ? "Skill 已更新" : "Skill 已创建", description: `${skillName} 已可用于 Agent 挂载。` });
    } catch (err) {
      const message = err instanceof Error ? err.message : "保存 Skill 失败";
      setError(message);
      toast({ tone: "danger", title: "保存 Skill 失败", description: message });
    } finally {
      setSaving(false);
    }
  }

  async function uploadZip(event: React.FormEvent) {
    event.preventDefault();
    if (!zipFile) {
      setError("请先选择 zip 压缩包");
      toast({ tone: "warn", title: "缺少文件", description: "请先选择 zip 包后再上传。" });
      return;
    }
    setUploading(true);
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
      toast({ tone: "success", title: "Skill 包上传成功", description: `${zipFile.name} 已完成解析。` });
    } catch (err) {
      const message = err instanceof Error ? err.message : "上传 Skill zip 失败";
      setError(message);
      toast({ tone: "danger", title: "上传 Skill 包失败", description: message });
    } finally {
      setUploading(false);
    }
  }

  async function removeSkill(skill: SkillConfig) {
    setBusySkillId(skill.id);
    try {
      await api.del(`/skills/${skill.id}`);
      await loadAll();
      toast({ tone: "success", title: "Skill 已删除", description: `${skill.name} 已从列表移除。` });
    } catch (err) {
      const message = err instanceof Error ? err.message : "删除 Skill 失败";
      setError(message);
      toast({ tone: "danger", title: "删除 Skill 失败", description: message });
    } finally {
      setBusySkillId(null);
    }
  }

  if (bootstrapping) {
    return (
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <Skeleton className="h-[820px]" />
        <div className="grid gap-6">
          <Skeleton className="h-[250px]" />
          <Skeleton className="h-[460px]" />
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <Card>
        <SectionTitle eyebrow="Prompt Assets" title="Skill 管理台" desc="沉淀可复用的提示片段、领域知识和工具说明，供 Agent 角色直接挂载。" />
        <div className="flex flex-wrap gap-2">
          <Badge>{skills.length} 个 Skill</Badge>
          <Badge tone="success">{skills.filter((skill) => skill.enabled).length} 个已启用</Badge>
          <Badge tone="warn">支持 zip 批量导入</Badge>
        </div>
      </Card>

      {error ? <InlineAlert tone="danger" title="Skill 页面操作失败" description={error} /> : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <Card>
          <SectionTitle eyebrow="Library" title="Skill 列表" desc="创建后的 Skill 会在 Agent 配置页直接可见，并参与 system prompt 组装。" />
          <div className="grid gap-3">
            {skills.map((skill) => (
              <div key={skill.id} className="rounded-[28px] border border-[var(--line)] bg-[var(--panel-2)] p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="text-lg font-semibold text-[var(--text)]">{skill.name}</div>
                      <Badge tone={skill.enabled ? "success" : "warn"}>{skill.enabled ? "enabled" : "disabled"}</Badge>
                      <Badge>{skill.source_type}</Badge>
                    </div>
                    <div className="mt-2 text-sm leading-7 text-[var(--muted)]">{skill.description}</div>
                    {skill.entry_file ? <div className="mt-3 text-xs text-[var(--muted)]">入口文件：{skill.entry_file}</div> : null}
                    {skill.package_path ? <div className="mt-1 break-all text-xs text-[var(--muted)]">包路径：{skill.package_path}</div> : null}
                    {skill.package_files?.length ? (
                      <details className="mt-3 rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-3">
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
                    <details className="mt-3 rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-3">
                      <summary className="cursor-pointer text-sm font-medium text-[var(--text)]">查看 Skill 内容</summary>
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
                      loading={busySkillId === skill.id}
                      onClick={() => {
                        if (!window.confirm(`确认删除 Skill “${skill.name}” 吗？`)) return;
                        void removeSkill(skill);
                      }}
                    >
                      删除
                    </SecondaryButton>
                  </div>
                </div>
              </div>
            ))}
            {!skills.length ? <EmptyState title="还没有 Skill" description="你可以手动创建一个 Skill，或直接上传 zip 包批量导入。" /> : null}
          </div>
        </Card>

        <div className="grid gap-6">
          <Card>
            <SectionTitle eyebrow="Upload" title="上传 Skill 压缩包" desc="支持上传 zip，后端会自动解压并识别 SKILL.md / README.md / .md / .txt 文件。" />
            <form onSubmit={uploadZip} className="space-y-4">
              <Field label="zip 文件" hint={zipFile ? zipFile.name : "仅支持 .zip"}>
                <Input type="file" accept=".zip" onChange={(e) => setZipFile(e.target.files?.[0] ?? null)} />
              </Field>
              <Field label="覆盖名称">
                <Input placeholder="可选：覆盖 Skill 名称" value={zipName} onChange={(e) => setZipName(e.target.value)} />
              </Field>
              <Field label="覆盖描述">
                <Input placeholder="可选：覆盖 Skill 描述" value={zipDescription} onChange={(e) => setZipDescription(e.target.value)} />
              </Field>
              <PrimaryButton type="submit" loading={uploading}>
                上传并解析 zip
              </PrimaryButton>
            </form>
          </Card>

          <Card>
            <SectionTitle eyebrow="Manual" title={form.id ? "编辑 Skill" : "创建 Skill"} desc="适合快速沉淀规则模板、提示片段与领域知识。" />
            <form onSubmit={saveSkill} className="space-y-4">
              <Field label="Skill 名称" required error={formErrors.name}>
                <Input name="name" placeholder="例如：数据分析助手规范" value={form.name} invalid={Boolean(formErrors.name)} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </Field>
              <Field label="Skill 描述" required error={formErrors.description}>
                <Input name="description" placeholder="简述该 Skill 的使用场景与收益" value={form.description} invalid={Boolean(formErrors.description)} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </Field>
              <Field label="Skill 内容" required error={formErrors.content}>
                <Textarea name="content" placeholder="输入 Skill 内容 / Prompt 片段" value={form.content} invalid={Boolean(formErrors.content)} onChange={(e) => setForm({ ...form, content: e.target.value })} />
              </Field>
              <CheckboxRow checked={form.enabled} onChange={(checked) => setForm({ ...form, enabled: checked })} label="启用 Skill" description="禁用后不会在 Agent 页面参与挂载。" />
              <div className="flex gap-3">
                <PrimaryButton type="submit" loading={saving}>
                  {form.id ? "保存 Skill" : "创建 Skill"}
                </PrimaryButton>
                {form.id ? (
                  <SecondaryButton type="button" onClick={() => setForm(emptySkill)}>
                    取消编辑
                  </SecondaryButton>
                ) : null}
              </div>
            </form>
          </Card>
        </div>
      </div>
    </div>
  );
}
