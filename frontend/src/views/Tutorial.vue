<template>
  <section class="section">
    <div class="level">
      <div class="level-left"><h1 class="title is-4">Tutorial</h1></div>
      <div class="level-right">
        <router-link class="button" to="/admin/dashboard">Back to dashboard</router-link>
      </div>
    </div>

    <div class="box">
      <h2 class="title is-6">Send your first campaign</h2>
      <p class="has-text-grey mb-4">
        Six steps, start to finish. Do them in order — a campaign with no list has nobody to
        send to, and a campaign with no working SMTP will fail at the last step.
      </p>

      <ol class="tutorial-steps">
        <li>
          <strong>Configure SMTP.</strong>&#32;<router-link to="/admin/settings">Settings → SMTP</router-link> — host, port, username
          and password from your mail provider. Set the default <em>from</em> address under
          Settings → General. Nothing sends until this works.
        </li>
        <li>
          <strong>Create a list.</strong>&#32;<router-link to="/admin/lists">Lists → + New List</router-link>. Pick
          <em>single opt-in</em> to mail everyone you add, or <em>double opt-in</em> to only mail
          people who click a confirmation link first.
        </li>
        <li>
          <strong>Add subscribers.</strong> One at a time via
          <router-link to="/admin/subscribers">Subscribers → + Add</router-link>, or in bulk via
          <router-link to="/admin/import">Import</router-link> with a CSV. On import choose the
          mode (<em>Subscribe</em>), the subscription status, and the target list. Columns are
          matched automatically — an export with <em>First Name / Last Name / E-Mail Address</em>
          works as-is; the import log shows which columns were used.
        </li>
        <li>
          <strong>Write the campaign.</strong>&#32;<router-link to="/admin/campaigns">Campaigns → + New Campaign</router-link>. Fill in
          Name (internal), Subject (what recipients see), Body, and — critically — the
          <em>Lists</em> field. Then <strong>Save</strong>. The campaign is now a draft.
        </li>
        <li>
          <strong>Test it.</strong> With the campaign saved, use <strong>Preview</strong> to see
          the rendered email and <strong>Send test</strong> to mail it to yourself. Test
          recipients must already exist as subscribers.
        </li>
        <li>
          <strong>Send.</strong> Hit <strong>Start sending</strong> and the campaign goes to
          <em>running</em>; the send engine works through the list in the background. You can
          <strong>Pause</strong> and resume, or <strong>Cancel</strong>. To send later, set
          <em>Send at</em>, save, then hit <strong>Schedule</strong>.
        </li>
      </ol>

      <p class="has-text-grey mt-4">
        Once it's running, views, clicks and bounces are counted on the campaign page itself.
      </p>
    </div>

    <div class="box">
      <h2 class="title is-6">What each section does</h2>
      <table class="table is-fullwidth">
        <tbody>
          <tr v-for="s in sections" :key="s.to">
            <td style="width: 160px">
              <router-link :to="s.to"><strong>{{ s.name }}</strong></router-link>
            </td>
            <td class="has-text-grey">{{ s.what }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="box">
      <h2 class="title is-6">Good to know</h2>
      <ul class="tutorial-notes has-text-grey">
        <li>
          <strong>Subject and body support template expressions</strong> —
          <!-- v-pre: the template syntax we're documenting is itself Vue interpolation. -->
          <code v-pre>{{ .Subscriber.FirstName }}</code> personalises each message.
        </li>
        <li>
          <strong>Draft → running → finished</strong> is the campaign lifecycle. Only drafts,
          paused and scheduled campaigns can be started; a finished campaign can't be re-sent.
        </li>
        <li>
          <strong>Blocklisted subscribers are never mailed</strong>, regardless of which lists
          they belong to. Unsubscribes and hard bounces land there automatically.
        </li>
        <li>
          <strong>Double opt-in lists only mail confirmed subscribers.</strong> If a send reaches
          far fewer people than expected, check the subscription status on the list.
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup lang="ts">
// Mirrors the sidebar in Layout.vue — keep the two in step if nav changes.
const sections = [
  { name: 'Dashboard', to: '/admin/dashboard', what: 'Counts at a glance and shortcuts into the common actions.' },
  { name: 'Subscribers', to: '/admin/subscribers', what: 'Everyone in the database. Search, edit, blocklist, or move people between lists.' },
  { name: 'Lists', to: '/admin/lists', what: 'The audiences you send to. Each is public or private, single or double opt-in.' },
  { name: 'Import', to: '/admin/import', what: 'Bulk-load subscribers from a CSV into a list, or bulk-blocklist them.' },
  { name: 'Campaigns', to: '/admin/campaigns', what: 'Write, test, schedule and send emails. Also where per-campaign stats live.' },
  { name: 'Templates', to: '/admin/templates', what: 'Reusable HTML wrappers for campaign bodies — header, footer, styling.' },
  { name: 'Media', to: '/admin/media', what: 'Uploaded images you can reference from campaign and template content.' },
  { name: 'Bounces', to: '/admin/bounces', what: 'Failed deliveries. Repeated hard bounces get the address blocklisted.' },
  { name: 'Users', to: '/admin/users', what: 'Admin accounts that can log in here. Not the same thing as subscribers.' },
  { name: 'Roles', to: '/admin/roles', what: 'Permission sets assigned to users, plus per-list access.' },
  { name: 'Settings', to: '/admin/settings', what: 'SMTP, sending performance, privacy, security, bounce handling and appearance.' },
  { name: 'Logs', to: '/admin/logs', what: 'Recent server log output — the first place to look when a send fails.' },
  { name: 'Maintenance', to: '/admin/maintenance', what: 'Housekeeping: prune orphan subscribers and clear old analytics data.' },
]
</script>

<style scoped>
.tutorial-steps {
  list-style: decimal;
  padding-left: 1.25rem;
}

.tutorial-steps li,
.tutorial-notes li {
  margin-bottom: 0.85rem;
  line-height: 1.6;
}

.tutorial-notes {
  list-style: disc;
  padding-left: 1.25rem;
}
</style>
