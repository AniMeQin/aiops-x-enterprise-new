{{- define "aiops-x.name" -}}aiops-x{{- end -}}
{{- define "aiops-x.fullname" -}}{{ .Release.Name }}{{- end -}}
{{- define "aiops-x.labels" -}}
app.kubernetes.io/name: {{ include "aiops-x.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}
{{- define "aiops-x.image" -}}
{{- $image := index . 0 -}}
{{- $root := index . 1 -}}
{{- if and $root.Values.productionEnforced (not $image.digest) -}}
{{- fail "productionEnforced requires every deployed image to be pinned by sha256 digest" -}}
{{- end -}}
{{- if $image.digest -}}
{{- printf "%s@%s" $image.repository $image.digest -}}
{{- else -}}
{{- printf "%s:%s" $image.repository $image.tag -}}
{{- end -}}
{{- end -}}
{{- define "aiops-x.podSecurityContext" -}}
runAsNonRoot: true
seccompProfile: {type: RuntimeDefault}
{{- end -}}
{{- define "aiops-x.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities: {drop: ["ALL"]}
{{- end -}}
{{- define "aiops-x.nginxSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
runAsNonRoot: true
runAsUser: 101
runAsGroup: 101
capabilities: {drop: ["ALL"]}
{{- end -}}
