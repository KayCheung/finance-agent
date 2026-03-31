import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SessionManager from '../../src/components/SessionManager.vue'

const pushMock = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
}))

const storeState = reactive({
  currentSessionId: 's-current',
  sessions: [
    { session_id: 's-p1', title: '置顶会话', preview: '置顶预览', pinned: true, archived: false, created_at: '', last_active: '', voucher_count: 0 },
    { session_id: 's-r1', title: '最近会话', preview: '最近预览', pinned: false, archived: false, created_at: '', last_active: '', voucher_count: 0 },
    { session_id: 's-a1', title: '归档会话', preview: '归档预览', pinned: false, archived: true, created_at: '', last_active: '', voucher_count: 0 },
  ],
  sessionSearchKeyword: '',
  includeArchived: false,
  fetchSessions: vi.fn().mockResolvedValue(undefined),
  newSession: vi.fn().mockResolvedValue(undefined),
  loadSession: vi.fn().mockResolvedValue(undefined),
  updateSession: vi.fn().mockResolvedValue(undefined),
  deleteSession: vi.fn().mockResolvedValue(undefined),
})

vi.mock('../../src/stores/session', () => ({
  useSessionStore: () => storeState,
}))

describe('SessionManager', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    storeState.includeArchived = false
    storeState.sessionSearchKeyword = ''
  })

  it('renders pinned and recent groups by default', async () => {
    const wrapper = mount(SessionManager)
    expect(wrapper.text()).toContain('置顶')
    expect(wrapper.text()).toContain('最近')
    expect(wrapper.text()).not.toContain('归档会话')
  })

  it('creates new session and navigates to reimbursement', async () => {
    const wrapper = mount(SessionManager)
    await wrapper.get('button.new-session-btn.mini').trigger('click')
    expect(storeState.newSession).toHaveBeenCalledTimes(1)
    expect(pushMock).toHaveBeenCalledWith({ name: 'reimbursement' })
  })

  it('searches sessions with includeArchived flag', async () => {
    const wrapper = mount(SessionManager)
    const input = wrapper.get('input.session-search')
    await input.setValue('差旅')
    await input.trigger('keyup.enter')
    expect(storeState.fetchSessions).toHaveBeenCalledWith('差旅', false)
  })

  it('toggles pin state', async () => {
    const wrapper = mount(SessionManager)
    const pinButton = wrapper.findAll('button.icon-btn').find((b: any) => b.text() === '置顶')
    expect(pinButton).toBeTruthy()
    await pinButton!.trigger('click')
    expect(storeState.updateSession).toHaveBeenCalledWith('s-r1', { pinned: true })
  })

  it('toggles archived visibility and allows unarchive', async () => {
    const wrapper = mount(SessionManager)
    const checkbox = wrapper.get('input[type="checkbox"]')
    await checkbox.setValue(true)
    expect(storeState.fetchSessions).toHaveBeenCalledWith('', true)
  })

  it('renames and deletes session', async () => {
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('新的标题')
    const wrapper = mount(SessionManager)

    const renameBtn = wrapper.findAll('button.icon-btn').find((b: any) => b.text() === '改名')
    expect(renameBtn).toBeTruthy()
    await renameBtn!.trigger('click')
    expect(storeState.updateSession).toHaveBeenCalledWith('s-p1', { title: '新的标题' })

    const deleteBtn = wrapper.findAll('button.icon-btn.danger')[0]
    expect(deleteBtn).toBeTruthy()
    await deleteBtn.trigger('click')
    expect(storeState.deleteSession).toHaveBeenCalled()

    promptSpy.mockRestore()
  })
})
