const { loadAllSchedules } = require('../utils/scheduler');

module.exports = {
  name: 'ready',
  once: true,
  execute(client) {
    console.log(`✅ تم تسجيل الدخول كـ ${client.user.tag}`);
    loadAllSchedules(client);
  },
};
