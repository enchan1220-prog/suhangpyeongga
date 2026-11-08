import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from storage import StorageError, export_backup, import_backup, load_local, make_snapshot, save_local, snapshot_hash


def is_cloud_mode() -> bool:
    try:
        return st.secrets.get("CLOUD_MODE", False) is True
    except StreamlitSecretNotFoundError:
        return False


def apply_pending_workspace(state) -> None:
    workspace = state.pop("pending_workspace", None)
    if workspace is None:
        return
    state.pop("example_revision", None)
    state.pop("auto_free", None)
    state.update(workspace)
    for name in ("add_revision", "edit_revision", "weekly_add_revision", "weekly_edit_revision", "special_add_revision", "special_edit_revision"):
        state[name] = state.get(name, 0) + 1
    for name in ("selected_task_id", "weekly_selected_id", "special_selected_id", "capacity_end_date", "restore_confirm", "backup_file"):
        state.pop(name, None)
    state["status_filter"] = "전체"


def render_storage_status() -> None:
    if is_cloud_mode():
        st.caption("웹 실행 중입니다. 수정 내용은 현재 세션에서 유지됩니다. 보관하려면 JSON 백업을 내려받으세요.")
        return
    current = snapshot_hash(make_snapshot(st.session_state))
    if st.session_state.get("local_saved_hash") == current:
        st.caption("현재 내용이 로컬 파일에 저장되어 있습니다.")
    else:
        st.warning("임시 저장 상태입니다. 변경 내용은 '저장과 백업' 탭에서 '로컬 저장'을 눌러야 남습니다.")


def render_storage() -> None:
    st.subheader("저장과 백업")
    cloud = is_cloud_mode()
    if cloud:
        st.caption("접속자별로 작업을 편집합니다. JSON 백업으로 내용을 보관하거나 복원할 수 있습니다.")
    else:
        st.caption("로컬 저장 파일은 data/workspace.json입니다. 예시 원본은 별도로 유지됩니다.")
    has_content = any(st.session_state[name] for name in ("tasks", "weekly_schedules", "special_schedules"))
    confirmed = not has_content or st.checkbox("불러올 내용으로 현재 화면을 바꿉니다", key="restore_confirm")
    if not cloud:
        render_local_storage(confirmed)
    try:
        backup = export_backup(st.session_state)
    except StorageError as error:
        st.error(str(error))
    else:
        st.download_button("JSON 백업 다운로드", data=backup, file_name="작업_백업.json", mime="application/json", key="backup_download")
    uploaded = st.file_uploader("JSON 백업 파일", type=["json"], key="backup_file")
    if st.button("백업 불러오기", key="backup_restore", disabled=uploaded is None or not confirmed):
        try:
            workspace = import_backup(uploaded.getvalue())
        except StorageError as error:
            st.error(str(error))
        else:
            st.session_state["pending_workspace"] = workspace
            st.session_state["notice"] = (
                "백업을 불러왔습니다. 현재 세션에서 사용할 수 있습니다."
                if cloud else "백업을 불러왔습니다. 이 컴퓨터에 남기려면 로컬 저장을 누르세요."
            )
            st.rerun()


def render_local_storage(confirmed: bool) -> None:
    columns = st.columns(2)
    with columns[0]:
        if st.button("로컬 저장", key="local_save", type="primary", width="stretch"):
            try:
                save_local(st.session_state)
            except StorageError as error:
                st.error(str(error))
            else:
                st.session_state["local_saved_hash"] = snapshot_hash(make_snapshot(st.session_state))
                st.session_state["notice"] = "이 컴퓨터의 로컬 파일에 저장했습니다."
                st.rerun()
    with columns[1]:
        if st.button("저장 파일 불러오기", key="local_load", disabled=not confirmed, width="stretch"):
            try:
                workspace = load_local()
            except StorageError as error:
                st.error(str(error))
            else:
                st.session_state["pending_workspace"] = workspace
                st.session_state["local_saved_hash"] = snapshot_hash(make_snapshot(workspace))
                st.session_state["notice"] = "저장된 자료를 불러왔습니다."
                st.rerun()
    st.caption("다른 PC로 옮길 때는 JSON 백업을 사용하세요. 여러 창의 변경 내용은 자동으로 합쳐지지 않습니다.")
