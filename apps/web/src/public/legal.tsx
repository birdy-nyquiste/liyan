/**
 * 隐私政策 and 使用条款 — documents rather than marketing copy.
 *
 * They live here rather than in `PublicSite.tsx` because they are long, and
 * because what they say has to be checked against the code rather than written
 * to sound right. Every factual claim below is one the implementation supports:
 * the 服务商 table is what `.env.example` actually configures and where each of
 * those services runs, the retention periods are `Settings`' cleanup defaults
 * (`cleanup_task_creation_session_ttl_hours`, `cleanup_source_edit_session_ttl_hours`,
 * `cleanup_deleted_task_retention_days`), and 第三章 is `apps/extension/manifest.ts`
 * in words.
 *
 * **When the code changes, these change with it.** A 服务商 added to the stack
 * or a retention default moved makes this page wrong, and a privacy policy that
 * disagrees with the product is worse than a short one. The Chrome Web Store
 * listing's data disclosures must also agree with 第三章 and 第四章 —
 * `docs/operations/publishing-the-extension.md` says which fields.
 *
 * The Chinese text is the document. `en` gets a notice saying so rather than a
 * translation, because two versions of a policy are two things that can
 * disagree and only one of them can govern.
 */
import type { ReactNode } from "react";

const CONTACT = "birdyyao@nyquiste.com";
const ENTITY = "Nyquiste Corporation（注册于美国弗吉尼亚州）";
const EFFECTIVE = "2026 年 9 月 8 日";
const UPDATED = "2026 年 9 月 8 日";

function Contact() {
  return <a href={`mailto:${CONTACT}`}>{CONTACT}</a>;
}

/** The dated preamble both documents open with. */
function Preamble({ children }: { children: ReactNode }) {
  return (
    <div className="site-legal-preamble">
      <p>
        <strong>
          生效日期：{EFFECTIVE}
          {"\u3000"}
          最近更新：{UPDATED}
        </strong>
      </p>
      {children}
    </div>
  );
}

function PrivacyPolicy() {
  return (
    <>
      <Preamble>
        <p>
          本政策由 {ENTITY}（下称“我们”）制定，适用于立言阁网页版工作台与立言阁浏览器插件
          （下称“插件”），二者合称“本服务”。
        </p>
        <p>
          <strong>请在使用本服务前完整阅读本政策，尤其是加粗部分。</strong>
          其中第三章说明插件在你的浏览器中的行为，第五章说明你的个人信息被存储和传输到了哪里。
          若你不同意本政策，请勿使用本服务。
        </p>
      </Preamble>

      <section>
        <h2>一、我们收集哪些信息，用于什么</h2>
        <p>
          我们只收集提供本服务所必需的信息。下表中标注“必需”的信息不提供则无法使用相应功能；
          标注“可选”的不提供不影响其余功能。
        </p>
        <div className="site-legal-table">
          <table>
            <thead>
              <tr>
                <th>场景</th>
                <th>信息类型</th>
                <th>目的</th>
                <th>必要性</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>注册与登录</td>
                <td>邮箱地址</td>
                <td>创建并识别你的账号，向你发送一次性登录验证码，把你提交的内容归属到你名下</td>
                <td>必需</td>
              </tr>
              <tr>
                <td>登录状态维持</td>
                <td>由身份服务商签发的会话令牌</td>
                <td>使你在有效期内无需重复登录</td>
                <td>必需</td>
              </tr>
              <tr>
                <td>提交来源</td>
                <td>
                  你粘贴的文本；你提交的公开网址，以及我们据此抓取到的网页正文、标题与出处；
                  你上传的文件，以及我们从中解析出的文本
                </td>
                <td>生成知言报告与立言文章</td>
                <td>必需（使用该功能时）</td>
              </tr>
              <tr>
                <td>主题与立言指令</td>
                <td>你填写的主题、你撰写的立言指令、你引用的报告条目</td>
                <td>决定文章的表达方向</td>
                <td>主题为可选；使用立言功能时指令为必需</td>
              </tr>
              <tr>
                <td>生成结果</td>
                <td>知言报告、立言文章及其修订记录</td>
                <td>向你呈现、供你继续编辑与发布</td>
                <td>必需</td>
              </tr>
              <tr>
                <td>额度与付费</td>
                <td>额度收支流水；由支付服务商返回的交易凭据（订单号、金额、状态、时间）</td>
                <td>结算额度、处理争议</td>
                <td>
                  必需（购买时）。
                  <strong>我们不接触也不存储你的银行卡号、有效期、安全码或支付密码。</strong>
                </td>
              </tr>
              <tr>
                <td>发布</td>
                <td>你选择的发布目标、你填写的作者署名、提交结果</td>
                <td>按你的指示向该目标提交文章</td>
                <td>必需（使用该功能时）</td>
              </tr>
              <tr>
                <td>服务运行与安全</td>
                <td>
                  请求日志（时间、接口路径、状态码、账号标识、IP 地址）、后台任务执行记录、
                  错误报告
                </td>
                <td>排查故障、防范滥用与攻击、履行法律义务</td>
                <td>必需</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p>
          <strong>我们不做的事：</strong>
          不使用广告追踪，不构建用于广告投放的用户画像，不在本服务中嵌入第三方统计分析脚本，
          不将你的内容用于训练我们自己或第三方的模型。
        </p>
        <p>
          <strong>关于错误报告。</strong>
          工作台的错误报告在离开你的浏览器之前会主动剥除内容载体——请求体、查询字符串、
          Cookie、鉴权头，以及你的邮箱地址；发送出去的是异常本身和一个账号标识。
          <strong>插件不包含任何错误上报机制。</strong>
        </p>
      </section>

      <section>
        <h2>二、本地存储与 Cookie</h2>
        <p>
          工作台在你的浏览器中保存登录会话、界面语言与显示模式偏好，以及尚未提交的草稿。
          这些存放于你自己的浏览器，用于让你刷新页面后不必重新登录、不丢失正在写的东西。
          清除浏览器数据即清除它们，代价是需要重新登录且未提交的草稿会丢失。
        </p>
        <p>我们不使用第三方 Cookie，不做跨站追踪。</p>
      </section>

      <section>
        <h2>三、浏览器插件</h2>
        <p>
          插件的用途只有一个：
          <strong>把你正在阅读的公开网页收集为来源，创建一个立言任务。</strong>
          围绕这一用途，它请求的是能完成它的最小权限组合。
        </p>
        <p>
          <strong>3.1 它读取什么。</strong> 仅在你点击浏览器工具栏上的插件图标之后，读取
          <strong>当前那一个标签页</strong>的网址和标题。这来自 Chrome 的{" "}
          <code>activeTab</code> 权限，其特点是临时授权而非长期授权：
          你离开该页面或关闭该标签页，授权即失效。
          <strong>
            插件不会在你未点击的情况下读取任何页面，不会记录你的浏览历史，
            也无法访问你的其他标签页。
          </strong>
        </p>
        <p>
          <strong>3.2 它不读取网页内容。</strong> 插件
          <strong>没有内容脚本（content script）</strong>
          ，不会读取、修改或向你访问的任何网页注入代码。
          网页正文是由立言阁的服务端根据你提交的那个网址自行抓取的——
          这与你在工作台里粘贴一个网址完全等价。
          这也意味着插件只能收集服务端本来就能抓取的公开页面：
          对于拒绝服务器访问、需要登录或付费才能阅读的页面，抓取会失败，
          即使你自己的浏览器能正常打开它。
        </p>
        <p>
          <strong>3.3 它在你本机存什么。</strong> 插件在 <code>chrome.storage.local</code>{" "}
          中只保存两项：<strong>你的登录会话</strong>，以及
          <strong>你正在填写的那个任务创建会话的编号</strong>。
          前者使你不必每次打开弹窗都重新登录；后者使你关闭弹窗、翻到下一个页面再打开时，
          已经收集的来源不会丢失。两项都保存在你自己的浏览器中，卸载插件即随之删除。
        </p>
        <p>
          <strong>3.4 它能连到哪里。</strong>{" "}
          插件声明了两个主机权限，均为立言阁自有服务：我们的 API，以及我们的身份服务项目。
          除这两个主机外，插件无法向任何地址发起网络请求。
        </p>
        <p>
          <strong>3.5 Chrome Web Store Limited Use 声明。</strong>
        </p>
        <blockquote>
          立言阁浏览器插件对用户数据的收集与使用符合 Chrome Web Store 的 Limited Use 要求：
          数据仅用于插件已声明的单一用途及与之直接相关的运作；不向任何第三方出售；
          不用于广告投放或信用评估；不用于与该用途无关的任何目的；
          除本政策第四章列明的服务商外，不允许人工读取，除非取得你的明示同意、
          为调查安全事件所必需，或为履行法律义务所必需。
        </blockquote>
      </section>

      <section>
        <h2>四、我们如何共享、转让、公开披露</h2>
        <p>
          <strong>4.1 服务商。</strong>{" "}
          下列服务商为本服务提供必要的基础设施。我们仅向其提供其功能所必需的最小信息，
          并通过合同要求其按我们的指示处理、不得用于自身目的。表中“所在地”
          即该信息实际被处理和存储的地区，与第五章一并阅读。
        </p>
        <div className="site-legal-table">
          <table>
            <thead>
              <tr>
                <th>服务商</th>
                <th>用途</th>
                <th>涉及的信息</th>
                <th>所在地</th>
                <th>其隐私政策</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Supabase</td>
                <td>身份与登录</td>
                <td>邮箱地址、会话令牌</td>
                <td>新加坡</td>
                <td>
                  <a href="https://supabase.com/privacy" target="_blank" rel="noreferrer">
                    supabase.com/privacy
                  </a>
                </td>
              </tr>
              <tr>
                <td>Render</td>
                <td>API、后台任务、数据库与消息队列的运行环境</td>
                <td>第一章列出的全部信息</td>
                <td>新加坡</td>
                <td>
                  <a href="https://render.com/privacy" target="_blank" rel="noreferrer">
                    render.com/privacy
                  </a>
                </td>
              </tr>
              <tr>
                <td>DeepSeek（杭州深度求索人工智能基础技术研究有限公司）</td>
                <td>生成知言报告与立言文章</td>
                <td>你提交的来源正文、主题、立言指令</td>
                <td>中国</td>
                <td>
                  <a href="https://platform.deepseek.com" target="_blank" rel="noreferrer">
                    platform.deepseek.com
                  </a>
                </td>
              </tr>
              <tr>
                <td>Cloudflare R2</td>
                <td>你上传的文件的存储</td>
                <td>上传的文件本身</td>
                <td>全球（Cloudflare 网络）</td>
                <td>
                  <a
                    href="https://www.cloudflare.com/privacypolicy/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    cloudflare.com/privacypolicy
                  </a>
                </td>
              </tr>
              <tr>
                <td>Vercel</td>
                <td>工作台前端托管</td>
                <td>访问日志</td>
                <td>全球（边缘网络）</td>
                <td>
                  <a
                    href="https://vercel.com/legal/privacy-policy"
                    target="_blank"
                    rel="noreferrer"
                  >
                    vercel.com/legal/privacy-policy
                  </a>
                </td>
              </tr>
              <tr>
                <td>Stripe</td>
                <td>支付处理</td>
                <td>支付所需信息（由 Stripe 直接向你收集）</td>
                <td>美国及其全球网络</td>
                <td>
                  <a href="https://stripe.com/privacy" target="_blank" rel="noreferrer">
                    stripe.com/privacy
                  </a>
                </td>
              </tr>
              <tr>
                <td>Sentry</td>
                <td>工作台错误报告</td>
                <td>已按第一章所述剥除内容后的错误记录</td>
                <td>美国</td>
                <td>
                  <a href="https://sentry.io/privacy/" target="_blank" rel="noreferrer">
                    sentry.io/privacy
                  </a>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p>
          <strong>你选择的发布目标</strong>在你发起提交时接收你的文章与署名。
          该目标对这些内容的处理适用其自身的规则，不受本政策约束。
        </p>
        <p>
          <strong>4.2 我们不出售个人信息</strong>
          ，不为定向广告或信用评估目的向第三方转让个人信息。
        </p>
        <p>
          <strong>4.3 其他披露情形。</strong>{" "}
          仅在为履行法律法规、监管要求或司法程序所必需，或为调查安全事件、
          滥用与违约行为所必需时披露，并在法律允许的范围内尽量事先告知你。
        </p>
        <p>
          <strong>4.4 主体变更。</strong>{" "}
          如发生合并、收购或资产转让，我们会在个人信息转移前告知接收方名称与联系方式，
          并要求其继续受本政策约束；如其变更处理目的，将重新征求你的同意。
        </p>
      </section>

      <section>
        <h2>五、存储地点、保存期限与跨境传输</h2>
        <p>
          <strong>5.1 我们是境外主体。</strong> Nyquiste Corporation 注册于美国弗吉尼亚州。
          <strong>
            这意味着你在使用本服务时，你的个人信息由一家中国境外的公司处理。
          </strong>
        </p>
        <p>
          <strong>5.2 存储地点。</strong> 本服务的服务器、数据库与后台任务运行于{" "}
          <strong>Render 新加坡区域</strong>；身份信息由 Supabase 存储于
          <strong>新加坡（ap-southeast-1）</strong>；你上传的文件存储于 Cloudflare R2
          的全球网络。
        </p>
        <p>
          <strong>5.3 跨境传输。</strong>{" "}
          <strong>
            你的个人信息会被传输至中国境外，并在境外被处理和存储；
            其中生成知言报告与立言文章所需的内容，会被传输给一家位于中国境内的第三方处理。
          </strong>
          每一位接收方的名称、用途、涉及的信息种类与所在地，均已在第四章的表格中逐项列明。
          这是本服务的核心机制，不存在替代路径——
          若你希望某段内容不离开你自己的设备，请不要把它作为来源提交。
        </p>
        <blockquote>
          <strong>需要向你说明的一点：</strong>
          依据《个人信息保护法》，向境外提供个人信息应当取得你的单独同意，
          即不与其他事项合并的、专门就此作出的同意。
          <strong>
            本服务目前通过本政策向你充分告知，尚未在界面上提供独立的单独同意环节。
          </strong>
          我们把这一点写在这里而不是隐去，是因为你有权知道当前的实际状况；
          我们计划在向受邀范围之外开放之前补上这一环节。
          在此之前，你可以随时按第七章行使你的权利，包括要求删除已提交的内容。
        </blockquote>
        <p>
          <strong>5.4 保存期限。</strong>
        </p>
        <div className="site-legal-table">
          <table>
            <thead>
              <tr>
                <th>数据</th>
                <th>保存期限</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>已收集但未确认创建任务的来源</td>
                <td>约 24 小时后自动清理。插件会在最早的一条临近清理时提醒你。</td>
              </tr>
              <tr>
                <td>未保存的来源编辑会话</td>
                <td>约 24 小时后自动清理</td>
              </tr>
              <tr>
                <td>你删除的任务及其内容</td>
                <td>保留约 30 天以便挽回误删，之后彻底清除</td>
              </tr>
              <tr>
                <td>请求日志与安全记录</td>
                <td>30 天</td>
              </tr>
              <tr>
                <td>账号与其余内容</td>
                <td>账号存续期间保留；账号注销后按 7.4 处理</td>
              </tr>
              <tr>
                <td>交易凭据</td>
                <td>按适用法律要求的期限保留</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2>六、我们如何保护你的信息</h2>
        <p>
          传输过程全程使用 TLS 加密。生产环境访问受最小权限控制，密钥不写入代码仓库。
          数据库定期备份。
        </p>
        <p>
          <strong>没有任何措施能保证绝对安全。</strong>
          如发生可能危害你权益的个人信息泄露，我们将及时向你告知涉及的信息种类、
          可能的影响、我们已采取的措施，以及你可以采取的应对建议，并依法向有关部门报告。
        </p>
      </section>

      <section>
        <h2>七、你的权利，以及如何行使</h2>
        <p>
          <strong>7.1 你享有的权利。</strong> 就我们持有的关于你的个人信息，你有权：
          <strong>查询与复制</strong>；<strong>要求更正或补充</strong>；
          <strong>要求删除</strong>；<strong>要求转移</strong>
          至你指定的其他处理者（在技术可行范围内）；<strong>撤回你此前给出的同意</strong>；
          <strong>要求我们解释本政策与个人信息处理规则</strong>。
        </p>
        <p>
          <strong>7.2 如何行使。</strong>{" "}
          大部分内容可在工作台中自行查看、编辑与删除。其余请发信至 <Contact />，
          写明你的注册邮箱和具体请求。
          为防止他人冒用，我们可能要求你从注册邮箱发信或完成其他必要的身份核验。
        </p>
        <p>
          <strong>7.3 我们的答复。</strong> 我们将在收到请求并完成身份核验后的{" "}
          <strong>15 个工作日</strong>内答复。若我们决定拒绝你的请求，将说明理由；
          你可按第十章的渠道投诉，或向有管辖权的监管部门或法院寻求救济。
        </p>
        <p>
          <strong>7.4 撤回同意与注销账号。</strong> 你可以随时撤回同意或注销账号。
          <strong>撤回对跨境传输的同意后，你将无法继续使用知言与立言功能</strong>
          ，因为这两项功能依赖第五章所述的传输。
          撤回与注销不影响此前基于你的同意已经进行的处理。
          账号注销后，我们将删除或匿名化你的个人信息，法律要求保留的记录除外。
        </p>
      </section>

      <section>
        <h2>八、未成年人</h2>
        <p>
          本服务面向成年用户，目前仅向受邀用户开放。
          我们不会有意收集不满十四周岁儿童的个人信息。
          若你是不满十四周岁儿童的监护人，且发现其在未经你同意的情况下使用了本服务，
          请与我们联系，我们将删除相关信息。
        </p>
      </section>

      <section>
        <h2>九、本政策的更新</h2>
        <p>
          我们可能更新本政策。政策更新时我们会修改本页顶部的“最近更新”日期。
          <strong>
            若更新涉及处理目的、信息种类、共享对象或跨境接收方的实质变化，
            我们会以显著方式另行通知你，并在必要时重新征求你的同意。
          </strong>
          你可以随时在本页查阅当前版本。
        </p>
      </section>

      <section>
        <h2>十、联系我们与投诉</h2>
        <p>{ENTITY}</p>
        <p>
          联系邮箱：
          <strong>
            <Contact />
          </strong>
        </p>
        <p>
          关于个人信息的任何询问、请求或投诉，均可发至上述邮箱，我们将在 15 个工作日内答复。
          若你对我们的答复不满意，可向有管辖权的监管部门投诉，或按
          <a href="/terms">《使用条款》</a>第十五章寻求司法救济。
        </p>
      </section>
    </>
  );
}

function TermsOfUse() {
  return (
    <>
      <Preamble>
        <p>
          本条款是你与 {ENTITY}（下称“我们”）之间关于使用立言阁的协议。
          <strong>
            注册账号或使用本服务，即表示你已阅读、理解并同意本条款及
            <a href="/privacy">隐私政策</a>。
          </strong>
          若你代表某一组织接受本条款，你声明你已获得该组织的授权。
        </p>
      </Preamble>

      <section>
        <h2>一、访问资格与账号</h2>
        <p>
          <strong>1.1</strong> 本服务目前<strong>仅向受邀用户开放</strong>
          。是否给予、维持或终止访问资格由我们决定。
          我们可以在不影响你既有权利的前提下调整开放范围。
        </p>
        <p>
          <strong>1.2</strong> 你应保证注册邮箱真实、有效且由你本人控制。
          登录使用一次性验证码，
          <strong>发送至你邮箱的验证码等同于你的身份凭证</strong>，请勿转交他人。
        </p>
        <p>
          <strong>1.3</strong> 你对通过你账号发生的一切行为负责。
          发现账号被他人使用，请立即通知我们。
        </p>
        <p>
          <strong>1.4</strong> 你应具备完全民事行为能力。
        </p>
      </section>

      <section>
        <h2>二、服务内容</h2>
        <p>
          <strong>2.1</strong> 立言阁将你提供的来源与主题整理为知言报告，
          按你撰写的立言指令生成文章，并可按你的指示向你选择的发布目标提交。
        </p>
        <p>
          <strong>2.2</strong> 部分功能（公开文章链接来源、上传文件来源）
          <strong>需你先购买过额度</strong>方可使用。
        </p>
        <p>
          <strong>2.3</strong> 我们可能增加、修改或停止任何功能。
          若停止的功能是你已付费依赖的，我们将按第三章处理。
        </p>
      </section>

      <section>
        <h2>三、额度与付费</h2>
        <p>
          <strong>3.1 计费依据。</strong> 额度按实际发生的工作计量与扣减。
          <strong>抓取失败、未产出任何结果的来源不消耗额度。</strong>
          已经完成的分析或写作，无论你是否满意其结果，均已发生并已计费——
          <strong>生成结果的质量不构成计费争议的依据</strong>。
        </p>
        <p>
          <strong>3.2 定价与变更。</strong> 价格以购买时页面展示为准。
          价格调整不影响你已购买的额度。
        </p>
        <p>
          <strong>3.3 支付。</strong> 支付由 Stripe 处理，并同时适用其条款。
        </p>
        <p>
          <strong>3.4 退款。</strong>{" "}
          <strong>额度一经购买，原则上不予退还</strong>
          ，因为购买后每一次分析与写作都会在第三方服务上产生我们无法收回的成本。
          <strong>若因我们的原因导致你无法使用已购买的额度</strong>
          ——例如服务长期不可用、我们停止了你依赖的功能，或出现重复扣款等差错——
          请联系 <Contact />，我们将个案核实并作出合理处理。
          适用法律赋予你的、不可通过约定排除的退款权利不受本条影响。
        </p>
        <p>
          <strong>3.5</strong> 额度不可转让，不可兑换现金，不计息。
        </p>
      </section>

      <section>
        <h2>四、你的内容</h2>
        <p>
          <strong>4.1 归属。</strong> 你提交的来源、主题、立言指令，
          以及由此生成的知言报告与立言文章，<strong>权利归你</strong>
          （第三方来源材料本身的权利仍归其权利人）。我们不因本服务取得你内容的所有权。
        </p>
        <p>
          <strong>4.2 你授予我们的许可。</strong> 为向你提供本服务，你授予我们一项
          <strong>非独占、免许可费、全球范围</strong>
          的许可，以存储、复制、传输、处理与向你展示你的内容，
          <strong>并将其提供给隐私政策第四章列明的服务商</strong>
          。该许可的范围严格限于提供本服务，随你删除内容或注销账号而终止
          （备份的正常清除周期除外）。
        </p>
        <p>
          <strong>4.3 你的保证。</strong> 你保证：你有权提交你所提交的内容；
          你提交的公开网址指向<strong>公开可读</strong>的页面；
          你的提交与后续发布不侵犯他人的著作权、商标权、隐私权、名誉权或其他权利，
          不违反适用法律。
        </p>
        <p>
          <strong>4.4</strong> 我们不对你的内容承担审查义务，
          但在收到有效侵权通知或发现违法内容时，可以移除相关内容并按第十二章处理。
        </p>
      </section>

      <section>
        <h2>五、生成内容</h2>
        <p>
          <strong>5.1</strong> 知言报告与立言文章由大型语言模型生成，
          <strong>可能包含错误、遗漏、过时信息或与事实不符的陈述</strong>。
        </p>
        <p>
          <strong>5.2</strong> 它们是
          <strong>供你使用的草稿，而非可以直接采信的结论</strong>
          。任何形式的核对、事实查证与责任判断，在你发布或依赖它们之前，都是你的责任。
        </p>
        <p>
          <strong>5.3</strong> 生成内容<strong>不构成</strong>
          法律、医疗、财务、投资或其他专业建议。
        </p>
        <p>
          <strong>5.4</strong> 由于模型的固有特性，不同用户就相似输入可能获得相似输出。
          我们不保证生成内容的独占性或可版权性。
        </p>
      </section>

      <section>
        <h2>六、使用规范</h2>
        <p>你不得：</p>
        <ol>
          <li>使用本服务绕过技术保护措施，或抓取需要登录、付费或授权才能阅读的内容；</li>
          <li>提交或生成违反适用法律的内容，包括但不限于侵权内容、违法信息；</li>
          <li>批量生成用于误导他人、伪造事实、操纵舆论或冒充他人的文字；</li>
          <li>规避、干扰或伪造额度计量；</li>
          <li>尝试访问其他用户的数据，或未经授权访问我们的系统；</li>
          <li>对本服务进行反向工程、自动化抓取、压力测试或以其他方式干扰其正常运行；</li>
          <li>未经我们书面同意，转售、转租或以其他方式向第三方提供本服务。</li>
        </ol>
      </section>

      <section>
        <h2>七、知识产权</h2>
        <p>
          除你的内容外，本服务及其全部组成部分——包括软件、界面、设计、文案、
          商标“立言阁”及相关标识——的知识产权归我们或相应权利人所有。
          本条款未明示授予的权利均予保留。你不得移除或遮蔽任何权利声明。
        </p>
      </section>

      <section>
        <h2>八、发布目标与第三方服务</h2>
        <p>
          <strong>8.1</strong> 向发布目标提交由<strong>你发起</strong>
          。提交是否成功、以及提交后内容如何被使用，由该目标决定，适用其自身的规则。
        </p>
        <p>
          <strong>8.2</strong>{" "}
          <strong>出现提交结果未知的情况时，立言阁不会自行重发</strong>
          ，以避免重复发布。是否再次提交由你判断。
        </p>
        <p>
          <strong>8.3</strong> 我们不对第三方服务或发布目标的行为承担责任。
        </p>
      </section>

      <section>
        <h2>九、服务可用性与免责</h2>
        <p>
          <strong>9.1</strong> 本服务按<strong>“现状”和“现有可用”</strong>
          提供。我们不承诺服务不中断、无错误，或能满足你的特定目的。
        </p>
        <p>
          <strong>9.2</strong> 我们会尽合理努力维持可用性，
          但可能因维护、升级、第三方服务故障或不可抗力而中断。
        </p>
      </section>

      <section>
        <h2>十、责任限制</h2>
        <p>
          <strong>10.1</strong> 在适用法律允许的最大范围内，我们不就
          <strong>间接、附随、特殊、后果性或惩罚性损失</strong>，以及
          <strong>
            利润损失、收入损失、数据损失、商誉损失或替代服务的采购成本
          </strong>
          承担责任，无论其基于合同、侵权或其他事由，
          也无论我们是否已被告知此类损失的可能性。
        </p>
        <p>
          <strong>10.2</strong> 在适用法律允许的最大范围内，我们就本条款及本服务承担的
          <strong>
            累计责任总额，不超过争议发生前十二（12）个月内你实际向我们支付的费用总额
          </strong>
          。
        </p>
        <p>
          <strong>10.3</strong> 上述限制<strong>不适用于</strong>
          ：我们的故意或重大过失；人身伤害或死亡；
          以及适用法律规定不得排除或限制的其他责任。
        </p>
      </section>

      <section>
        <h2>十一、赔偿</h2>
        <p>
          因你违反本条款、或因你的内容侵犯第三方权利而使我们遭受索赔、损失或费用
          （含合理的律师费），你应予赔偿。
        </p>
      </section>

      <section>
        <h2>十二、中止与终止</h2>
        <p>
          <strong>12.1</strong> 你可以随时停止使用并注销账号。
        </p>
        <p>
          <strong>12.2</strong> 若你实质违反本条款、
          你的使用给我们或他人带来法律风险或安全风险，我们可以中止或终止你的访问。
          <strong>除紧急情形或法律禁止外，我们会事先告知并给你合理的改正机会。</strong>
        </p>
        <p>
          <strong>12.3</strong> 终止后：你的内容按隐私政策的保存期限处理；
          已发生的付款按第 3.4 条处理；
          第四、五、七、十、十一、十五章在终止后继续有效。
        </p>
      </section>

      <section>
        <h2>十三、不可抗力</h2>
        <p>
          因自然灾害、战争、罢工、政府行为、网络或电力中断、第三方基础设施重大故障等
          不可抗力或不可归责于我们的原因导致的不能履行或迟延履行，我们不承担责任，
          但会及时告知并尽力减轻影响。
        </p>
      </section>

      <section>
        <h2>十四、通知</h2>
        <p>
          我们通过你的注册邮箱或在本服务内显著位置向你发出通知，自发出之日视为送达。
          你向我们的通知应发至 <Contact />。请保持注册邮箱可用。
        </p>
      </section>

      <section>
        <h2>十五、适用法律与争议解决</h2>
        <p>
          <strong>15.1</strong> 本条款的订立、效力、解释、履行及争议解决，均适用
          <strong>美国弗吉尼亚州法律</strong>，不适用其冲突法规则。
        </p>
        <p>
          <strong>15.2</strong> 因本条款或本服务产生的争议，双方应先友好协商；
          协商不成的，任何一方可向<strong>美国弗吉尼亚州有管辖权的法院</strong>
          提起诉讼，双方同意接受该法院的管辖。
        </p>
        <p>
          <strong>15.3</strong>{" "}
          上述约定不排除适用法律强制赋予你的、在你住所地寻求救济的权利。
        </p>
      </section>

      <section>
        <h2>十六、其他</h2>
        <p>
          <strong>16.1 条款变更。</strong> 我们可能修改本条款。
          修改后我们会更新“最近更新”日期；
          <strong>实质性修改将通过邮件或服务内通知另行告知</strong>
          ，并在通知中说明生效时间。你在生效后继续使用即视为接受；
          不接受的，请停止使用并注销账号。
        </p>
        <p>
          <strong>16.2 可分割性。</strong>{" "}
          某一条款被认定无效或不可执行的，不影响其余条款的效力。
        </p>
        <p>
          <strong>16.3 不弃权。</strong> 我们未行使某项权利，不构成对该权利的放弃。
        </p>
        <p>
          <strong>16.4 完整协议。</strong>{" "}
          本条款与隐私政策构成你与我们之间就本服务达成的完整协议，
          取代此前的口头或书面沟通。
        </p>
        <p>
          <strong>16.5 转让。</strong> 你不得转让本条款下的权利义务。
          我们可在合并、收购或资产转让中转让本条款，并事先告知你。
        </p>
        <p>
          <strong>16.6 标题与语言。</strong> 各章标题仅为便于阅读，不影响解释。
          <strong>本条款以中文版本为准</strong>，其他语言译本仅供参考。
        </p>
      </section>

      <section>
        <h2>十七、联系我们</h2>
        <p>
          {ENTITY}
          {"\u3000"}邮箱：
          <strong>
            <Contact />
          </strong>
        </p>
      </section>
    </>
  );
}

/**
 * The notice the English view gets instead of a translation.
 *
 * Not a courtesy: 使用条款 16.6 says the Chinese version governs, and shipping
 * an English rendering beside it would be publishing a second document that can
 * disagree with the one that does.
 */
const EN_NOTICE = `This document is published in Chinese, which is the version that governs. If you need it in English, write to ${CONTACT}.`;

/** One legal document. */
export function LegalDocument({ kind, en }: { kind: "privacy" | "terms"; en: boolean }): ReactNode {
  const title = kind === "privacy" ? "隐私政策" : "使用条款";
  const titleEn = kind === "privacy" ? "Privacy Policy" : "Terms of Use";
  return (
    <>
      <h1>{en ? titleEn : title}</h1>
      {en ? <p className="site-legal-notice">{EN_NOTICE}</p> : null}
      {kind === "privacy" ? <PrivacyPolicy /> : <TermsOfUse />}
    </>
  );
}
