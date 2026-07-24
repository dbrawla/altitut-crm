import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createOruga, OrugaComponentPlugins } from '@oruga-ui/oruga-next'
import { bulmaConfig } from '@oruga-ui/theme-bulma'
import App from './App.vue'
import router from './router'
// Load order matters. main.css carries the custom shell (.sidebar-*, .btn, .card
// used by Layout/Login/NotFound). Bulma base MUST load — without it every Oruga
// component (.table/.button/.modal/.select) renders as unstyled text. Bulma comes
// after main.css so its component classes win the .table/.modal/.pagination
// collisions; brand.css comes last so its :root retint beats Bulma's defaults.
import './assets/main.css'
import 'bulma/css/bulma.min.css'
import '@oruga-ui/theme-bulma/style.css'
import './assets/brand.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
// Oruga (Vue 3 successor to Buefy) with the Bulma theme. The default export is
// `createOruga()` with an EMPTY component list, so `app.use(Oruga, bulmaConfig)`
// sets the config but registers zero components — every <o-table>/<o-button> then
// renders as an unstyled unknown element. Pass OrugaComponentPlugins explicitly so
// all components are actually registered.
app.use(createOruga(bulmaConfig, OrugaComponentPlugins))

app.mount('#app')
